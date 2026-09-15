from __future__ import annotations

import hashlib
import re
from datetime import datetime
from urllib.parse import urljoin

import requests
from bs4 import BeautifulSoup

from .base import CollectionResult, new_session
from ..models import Permit


DEVELOPMENT_SIGNALS = (
    "annex",
    "commercial",
    "conditional use",
    "development agreement",
    "final plat",
    "mixed use",
    "mixed-use",
    "multifamily",
    "preliminary plat",
    "site plan",
    "subdivision",
    "townhome",
    "zone change",
)

EXCLUDED_SIGNALS = (
    "drc minutes",
    "general plan update",
    "meeting minutes",
)


class SalemCollector:
    name = "Salem"
    SCOPE_ID = "pmn-drc-project-decisions-v1"
    public_body_url = "https://www.utah.gov/pmn/sitemap/publicbody/7083.html"
    notices_url = public_body_url
    MAX_NOTICE_PAGES = 12

    def collect(self, session: requests.Session | None = None) -> CollectionResult:
        session = session or new_session()
        response = session.get(self.public_body_url, timeout=45)
        response.raise_for_status()
        notice_urls = self.discover_notice_urls(response.text, response.url)

        permits: list[Permit] = []
        errors: list[str] = []
        for notice_url in notice_urls[: self.MAX_NOTICE_PAGES]:
            try:
                notice = session.get(notice_url, timeout=45)
                notice.raise_for_status()
                permits.extend(self.parse_notice_page(notice.text, notice.url))
            except Exception as exc:
                errors.append(f"{type(exc).__name__}: {exc}")

        by_key: dict[str, Permit] = {}
        for permit in permits:
            old = by_key.get(permit.key)
            if old is None or permit.issued_date > old.issued_date:
                by_key[permit.key] = permit
        permits = sorted(
            by_key.values(),
            key=lambda p: (p.issued_date, p.project_name or ""),
            reverse=True,
        )
        if not permits:
            detail = "; ".join(errors) if errors else "no project-specific DRC items parsed"
            raise RuntimeError(f"Salem DRC source returned no usable records: {detail}")

        newest = max(p.issued_date for p in permits)
        note = (
            "Official Utah Public Notice Salem Development Review Committee agendas; "
            f"{len(permits)} project-specific development item(s), latest project meeting {newest}; "
            "minutes and general-plan-only items excluded; planning/development-stage intelligence only"
        )
        if errors:
            note += f"; {len(errors)} notice page(s) unavailable"

        return CollectionResult(
            self.name,
            permits,
            self.public_body_url,
            note,
            scope_id=self.SCOPE_ID,
        )

    @classmethod
    def discover_notice_urls(cls, html: str, source_url: str) -> list[str]:
        soup = BeautifulSoup(html, "html.parser")
        found: list[str] = []
        seen: set[str] = set()
        for anchor in soup.find_all("a", href=True):
            href = anchor.get("href", "")
            if "/pmn/sitemap/notice/" not in href:
                continue
            text = cls._clean(" ".join(anchor.stripped_strings)).lower()
            if "salem city drc" not in text:
                continue
            url = urljoin(source_url, href)
            if url in seen:
                continue
            seen.add(url)
            found.append(url)
        return found

    @classmethod
    def parse_notice_page(cls, html: str, source_url: str) -> list[Permit]:
        soup = BeautifulSoup(html, "html.parser")
        text = cls._clean(soup.get_text(" ", strip=True))
        event_date = cls._event_date(text)
        description = cls._description(text)
        if not event_date or not description:
            return []

        permits: list[Permit] = []
        for item in cls._agenda_items(description):
            normalized = item.lower()
            if any(signal in normalized for signal in EXCLUDED_SIGNALS):
                continue
            project_code = cls._project_code(item)
            if not project_code and not any(signal in normalized for signal in DEVELOPMENT_SIGNALS):
                continue

            stable = project_code or cls._stable_title(item)
            digest = hashlib.sha1(stable.lower().encode("utf-8")).hexdigest()[:12].upper()
            permits.append(
                Permit(
                    state="UT",
                    jurisdiction=cls.name,
                    permit_number=f"SAL-PLAN-{project_code or digest}",
                    issued_date=event_date,
                    permit_type=cls._permit_type(item),
                    address=cls._address(item),
                    project_name=cls._stable_title(item),
                    status="Development Review Committee",
                    source_name="Utah Public Notice - Salem Development Review Committee",
                    source_url=source_url,
                    raw={
                        "lead_stage": "PLANNING",
                        "meeting_date": event_date,
                        "date_semantics": "scheduled_drc_meeting_date",
                        "project_code": project_code,
                        "agenda_item": item,
                    },
                )
            )
        return permits

    @staticmethod
    def _clean(value: str) -> str:
        return re.sub(r"\s+", " ", value or "").strip(" .")

    @staticmethod
    def _event_date(text: str) -> str | None:
        match = re.search(
            r"Event Start Date & Time\s+([A-Za-z]+\s+\d{1,2},\s+\d{4})",
            text,
            flags=re.I,
        )
        if not match:
            return None
        try:
            return datetime.strptime(match.group(1), "%B %d, %Y").date().isoformat()
        except ValueError:
            return None

    @classmethod
    def _description(cls, text: str) -> str:
        match = re.search(
            r"Description/Agenda\s+(.*?)(?:Notice of Special Accommodations|Meeting Information|Notice Posting Details|Download Attachments|$)",
            text,
            flags=re.I,
        )
        return cls._clean(match.group(1)) if match else ""

    @classmethod
    def _agenda_items(cls, description: str) -> list[str]:
        matches = re.findall(
            r"(?:^|\s)\d+\.\s+(?:Decision:\s*)?(.*?)(?=\s+\d+\.\s+(?:Decision:\s*)?|$)",
            description,
            flags=re.I,
        )
        return [cls._clean(item) for item in matches if cls._clean(item)]

    @staticmethod
    def _project_code(item: str) -> str | None:
        match = re.search(r"\b(?:PP|FP|SP|PZ)\d{2,4}-\d{3,6}\b", item, flags=re.I)
        return match.group(0).upper() if match else None

    @classmethod
    def _stable_title(cls, item: str) -> str:
        text = cls._clean(item)
        text = re.sub(r"^(?:Decision:\s*)", "", text, flags=re.I)
        return cls._clean(text)

    @staticmethod
    def _permit_type(item: str) -> str:
        lowered = item.lower()
        if "preliminary plat" in lowered:
            return "Planning Preliminary Plat"
        if "final plat" in lowered:
            return "Planning Final Plat"
        if "site plan" in lowered:
            return "Planning Site Plan"
        if "zone change" in lowered:
            return "Planning Rezone"
        if "development agreement" in lowered:
            return "Planning Development Agreement"
        if "conditional use" in lowered:
            return "Planning Conditional Use"
        if "annex" in lowered:
            return "Planning Annexation"
        if "subdivision" in lowered:
            return "Planning Subdivision/Plat"
        return "Planning Review"

    @classmethod
    def _address(cls, item: str) -> str:
        match = re.search(
            r"\b\d{2,5}\s+(?:North|South|East|West|N|S|E|W)\s+[A-Za-z0-9 .'-]+",
            item,
            flags=re.I,
        )
        return cls._clean(match.group(0)) if match else ""
