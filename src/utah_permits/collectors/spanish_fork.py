from __future__ import annotations

import hashlib
import re
from datetime import datetime, timezone
from urllib.parse import urljoin

import requests
from bs4 import BeautifulSoup

from .base import CollectionResult, new_session
from ..models import Permit


APPLICATION_CODES = {
    "AN": "Annexation",
    "GP": "General Plan Amendment",
    "PP": "Preliminary Plat",
    "CUP": "Conditional Use Permit",
    "MP": "Minor Plat Amendment",
    "SP": "Site Plan",
    "FP": "Final Plat",
    "MS": "Minor Subdivision Amendment",
    "ZA": "Zone Change",
    # The City's page also uses these codes but does not define them in its key.
    # Preserve them without inventing an expansion.
    "RPP": "Planning Application (RPP)",
    "RFP": "Planning Application (RFP)",
}


class SpanishForkCollector:
    name = "Spanish Fork"
    SCOPE_ID = "current-projects+growth-context-v1"
    projects_url = (
        "https://cms.spanishfork.org/revize/spanishforkut/departments/"
        "community_development/current_projects.php"
    )
    growth_url = (
        "https://cms.spanishfork.org/revize/spanishforkut/departments/"
        "community_development/planning/growth.php"
    )
    # Used by generic failed-source reporting.
    landing_url = projects_url

    def collect(self, session: requests.Session | None = None) -> CollectionResult:
        session = session or new_session()
        snapshot_date = datetime.now(timezone.utc).date().isoformat()

        response = session.get(self.projects_url, timeout=45)
        response.raise_for_status()
        permits = self.parse_projects_html(response.text, response.url, snapshot_date)
        if not permits:
            raise RuntimeError("No Spanish Fork current projects were parsed")

        growth_note = ""
        try:
            growth = session.get(self.growth_url, timeout=45)
            growth.raise_for_status()
            stats = self.parse_growth_html(growth.text)
            if stats:
                parts: list[str] = []
                as_of = stats.get("as_of")
                if as_of:
                    parts.append(f"growth statistics as of {as_of}")
                if stats.get("total_building_permits") is not None:
                    parts.append(f"{stats['total_building_permits']} total 2026 building permits")
                if stats.get("single_family_permits") is not None:
                    parts.append(f"{stats['single_family_permits']} single-family")
                if stats.get("multi_unit_permits") is not None:
                    parts.append(f"{stats['multi_unit_permits']} multi-unit")
                if parts:
                    growth_note = "; " + ", ".join(parts)
        except Exception as exc:
            growth_note = f"; growth context unavailable ({type(exc).__name__}: {exc})"

        return CollectionResult(
            self.name,
            permits,
            self.projects_url,
            (
                "Official Spanish Fork Current Projects list; "
                f"{len(permits)} active development application(s) observed {snapshot_date}; "
                "planning/development-stage intelligence only"
                f"{growth_note}"
            ),
            scope_id=self.SCOPE_ID,
        )

    @classmethod
    def parse_projects_html(
        cls,
        html: str,
        source_url: str,
        snapshot_date: str,
    ) -> list[Permit]:
        soup = BeautifulSoup(html, "html.parser")
        heading = None
        for tag in soup.find_all(["h2", "h3", "h4"]):
            text = cls._clean(tag.get_text(" ", strip=True))
            if text.lower().startswith("current projects"):
                heading = tag
                break
        if heading is None:
            raise RuntimeError("Spanish Fork Current Projects section was not found")

        permits: list[Permit] = []
        seen: set[str] = set()

        for node in heading.find_all_next():
            if node is not heading and getattr(node, "name", None) in {"h2", "h3", "h4"}:
                section_text = cls._clean(node.get_text(" ", strip=True)).lower()
                if section_text.startswith("completed project applications"):
                    break

            if getattr(node, "name", None) != "a" or not node.get("href"):
                continue
            title = cls._clean(node.get_text(" ", strip=True))
            if not title:
                continue
            code = cls._application_code(title)
            if not code:
                continue

            detail_url = urljoin(source_url, node["href"])
            stable = f"{title}|{detail_url}".lower()
            digest = hashlib.sha1(stable.encode("utf-8")).hexdigest()[:12].upper()
            permit_number = f"SF-PLAN-{digest}"
            if permit_number in seen:
                continue
            seen.add(permit_number)

            project_name = re.sub(rf"\s+{re.escape(code)}$", "", title, flags=re.I).strip()
            permits.append(
                Permit(
                    state="UT",
                    jurisdiction=cls.name,
                    permit_number=permit_number,
                    issued_date=snapshot_date,
                    permit_type=APPLICATION_CODES.get(code, f"Planning Application ({code})"),
                    address="",
                    project_name=project_name or title,
                    status="Current Development Application",
                    source_name="Spanish Fork Current Projects",
                    source_url=detail_url,
                    raw={
                        "lead_stage": "PLANNING",
                        "application_code": code,
                        "source_snapshot_date": snapshot_date,
                        "date_semantics": "source_snapshot_date",
                        "project_category": cls._project_category(project_name or title),
                    },
                )
            )

        return sorted(permits, key=lambda p: (p.project_name or "", p.permit_number))

    @classmethod
    def parse_growth_html(cls, html: str) -> dict[str, int | str]:
        text = cls._clean(BeautifulSoup(html, "html.parser").get_text(" ", strip=True))
        stats: dict[str, int | str] = {}

        as_of = re.search(
            r"All data accurate as of\s+([A-Za-z]+\s+\d{1,2},\s+20\d{2})",
            text,
            flags=re.I,
        )
        if as_of:
            stats["as_of"] = as_of.group(1)

        patterns = {
            "total_building_permits": r"Total Building Permits\s+(\d[\d,]*)",
            "single_family_permits": r"Permits for Single-family Homes\s+(\d[\d,]*)",
            "multi_unit_permits": r"Permits for Multi-unit Homes\s+(\d[\d,]*)",
        }
        for key, pattern in patterns.items():
            match = re.search(pattern, text, flags=re.I)
            if match:
                stats[key] = int(match.group(1).replace(",", ""))
        return stats

    @staticmethod
    def _application_code(title: str) -> str | None:
        match = re.search(r"\b([A-Z]{2,3})$", title.strip(), flags=re.I)
        if not match:
            return None
        code = match.group(1).upper()
        return code if code in APPLICATION_CODES else None

    @staticmethod
    def _project_category(project: str) -> str:
        text = project.lower()
        if any(term in text for term in ("townhome", "townhomes", "apartment", "apartments", "duplex")):
            return "Multifamily"
        if any(
            term in text
            for term in (
                "business park",
                "professional plaza",
                "printing",
                "storage",
                "auto sales",
                "commercial",
                "office",
                "hotel",
                "retail",
            )
        ):
            return "Commercial"
        if "subdivision" in text or "estates" in text or "village" in text:
            return "Residential"
        return "Other"

    @staticmethod
    def _clean(value: str) -> str:
        return re.sub(r"\s+", " ", value or "").strip()
