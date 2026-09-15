from __future__ import annotations

import calendar
import hashlib
import re
from datetime import date
from urllib.parse import urljoin

import requests
from bs4 import BeautifulSoup

from .base import CollectionResult, new_session
from ..models import Permit


UPDATED_RE = re.compile(
    r"^(?P<project>.+?),\s*Planner:\s*(?P<planner>.+?)\s*\(updated\s+"
    r"(?P<month>[A-Za-z]+)\s+(?P<year>20\d{2})\)\s*$",
    flags=re.I,
)


class SaratogaSpringsCollector:
    name = "Saratoga Springs"
    SCOPE_ID = "pending-planning-applications-v1"
    applications_url = "https://www.saratogasprings-ut.gov/229/Applications-Pending-Recently-Approved"

    def collect(self, session: requests.Session | None = None) -> CollectionResult:
        session = session or new_session()
        response = session.get(self.applications_url, timeout=45)
        response.raise_for_status()
        permits = self.parse_page(response.text, response.url)
        newest = max((p.issued_date for p in permits), default="unknown")
        return CollectionResult(
            self.name,
            permits,
            self.applications_url,
            (
                "Official Saratoga Springs Applications Pending & Recently Approved page; "
                f"{len(permits)} pending development application(s), newest update {newest}; "
                "planning-stage intelligence only"
            ),
            scope_id=self.SCOPE_ID,
        )

    @classmethod
    def parse_page(cls, html: str, source_url: str) -> list[Permit]:
        soup = BeautifulSoup(html, "html.parser")
        permits: list[Permit] = []
        seen: set[str] = set()

        # Pending applications use the City's explicit "updated Month YYYY" label.
        # Recently approved applications instead use "approved Month YYYY", so this
        # deliberately excludes them and keeps the source focused on live pipeline.
        for item in soup.find_all("li"):
            text = " ".join(item.stripped_strings)
            match = UPDATED_RE.match(text)
            if not match:
                continue

            project = re.sub(r"\s+", " ", match.group("project")).strip()
            planner = re.sub(r"\s+", " ", match.group("planner")).strip()
            month = cls._month_number(match.group("month"))
            year = int(match.group("year"))
            updated = date(year, month, 1).isoformat()
            detail_anchor = item.find("a", href=True)
            detail_url = urljoin(source_url, detail_anchor["href"]) if detail_anchor else source_url
            category = cls._category(project)

            digest = hashlib.sha1(
                f"{project}|{planner}|{updated}".lower().encode("utf-8")
            ).hexdigest()[:12].upper()
            permit_number = f"SARATOGA-PLAN-{digest}"
            if permit_number in seen:
                continue
            seen.add(permit_number)

            permits.append(
                Permit(
                    state="UT",
                    jurisdiction=cls.name,
                    permit_number=permit_number,
                    issued_date=updated,
                    permit_type="Planning Application",
                    address="",
                    project_name=project,
                    status="Under Plan Review",
                    source_name="Saratoga Springs Pending Applications",
                    source_url=detail_url,
                    raw={
                        "project": project,
                        "planner": planner,
                        "application_category": category,
                        "updated_month": updated,
                        "date_semantics": "source_updated_month",
                        "lead_stage": "PLANNING",
                    },
                )
            )

        if not permits:
            raise RuntimeError("No current Saratoga Springs pending applications were parsed")
        return permits

    @staticmethod
    def _month_number(value: str) -> int:
        token = value.strip().lower()
        full = {name.lower(): number for number, name in enumerate(calendar.month_name) if name}
        if token in full:
            return full[token]

        # CivicPlus source content occasionally carries harmless month typos such
        # as "Augusts". Match the canonical three-letter month prefix rather than
        # failing the whole collector over a trailing character.
        prefix = token[:3]
        abbreviated = {
            name.lower(): number for number, name in enumerate(calendar.month_abbr) if name
        }
        month = abbreviated.get(prefix)
        if not month:
            raise ValueError(f"Unknown month: {value}")
        return month

    @staticmethod
    def _category(project: str) -> str:
        text = project.lower()
        if any(term in text for term in ("mixed-use", "mixed use")):
            return "Mixed-Use"
        if any(term in text for term in ("commercial", "office", "retail", "warehouse", "hotel", "industrial")):
            return "Commercial"
        if any(term in text for term in ("school", "church", "civic", "institutional", "hospital", "medical")):
            return "Civic/Institutional"
        return "Residential/Other"
