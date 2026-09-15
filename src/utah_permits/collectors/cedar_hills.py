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
    "commercial development",
    "development agreement",
    "final plat",
    "mixed use",
    "mixed-use",
    "plat ",
    "preliminary plan",
    "preliminary plat",
    "rezone",
    "rezoning",
    "site plan",
    "subdivision",
    "townhome",
)

POLICY_ONLY_SIGNALS = (
    "accessory dwelling",
    "approval of the minutes",
    "city code",
    "meeting schedule",
    "open and public meetings",
    "rear setback",
    "setback area",
    "signs",
    "zoning map",
)


class CedarHillsCollector:
    name = "Cedar Hills"
    SCOPE_ID = "pmn-planning-projects-v1"
    public_body_url = "https://www.utah.gov/pmn/sitemap/publicbody/434.html"
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

        by_project: dict[str, Permit] = {}
        for permit in permits:
            old = by_project.get(permit.permit_number)
            if old is None or permit.issued_date > old.issued_date:
                by_project[permit.permit_number] = permit

        permits = sorted(
            by_project.values(),
            key=lambda p: (p.issued_date, p.project_name or ""),
            reverse=True,
        )
        if not permits:
            detail = "; ".join(errors) if errors else "no project-specific Planning Commission items parsed"
            raise RuntimeError(f"Cedar Hills planning source returned no usable records: {detail}")

        newest = max(p.issued_date for p in permits)
        note = (
            "Official Utah Public Notice Cedar Hills Planning Commission agendas; "
            f"{len(permits)} project-specific development item(s), latest substantive project meeting {newest}; "
            "code/zoning-policy and administrative items excluded; planning/development-stage intelligence only. "
            "The City commercial-development page separately says several approved projects are in various stages of construction, "
            "but its map does not expose a dependable project-by-project text feed, so those are not converted into permit rows."
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
            if "planning commission" not in text:
                continue
            if "cancel" in text or "schedule" in text:
                continue
            url = urljoin(source_url, href)
            if url not in seen:
                seen.add(url)
                found.append(url)
        return found

    @classmethod
    def parse_notice_page(cls, html: str, source_url: str) -> list[Permit]:
        soup = BeautifulSoup(html, "html.parser")
        text = cls._clean(soup.get_text(" ", strip=True))
        lowered = text.lower()
        if "cancelled" in lowered or "canceled" in lowered:
            return []

        event_date = cls._event_date(text)
        description = cls._description(text)
        if not event_date or not description:
            return []

        permits: list[Permit] = []
        for item in cls._agenda_items(description):
            normalized = item.lower()
            if any(signal in normalized for signal in POLICY_ONLY_SIGNALS):
                continue
            if not any(signal in normalized for signal in DEVELOPMENT_SIGNALS):
                continue

            title = cls._stable_title(item)
            digest = hashlib.sha1(title.lower().encode("utf-8")).hexdigest()[:12].upper()
            permits.append(
                Permit(
                    state="UT",
                    jurisdiction=cls.name,
                    permit_number=f"CDH-PLAN-{digest}",
                    issued_date=event_date,
                    permit_type=cls._permit_type(item),
                    address=cls._address(item),
                    project_name=title,
                    units=cls._units(item),
                    status="Planning Commission Agenda",
                    source_name="Utah Public Notice - Cedar Hills Planning Commission",
                    source_url=source_url,
                    raw={
                        "lead_stage": "PLANNING",
                        "meeting_date": event_date,
                        "date_semantics": "scheduled_planning_meeting_date",
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
        body_match = re.search(
            r"SCHEDULED ITEMS\s*&?\s*PUBLIC HEARINGS\s*(.*?)(?:\s+ADJOURNMENT|$)",
            description,
            flags=re.I,
        )
        body = body_match.group(1) if body_match else description
        matches = re.findall(
            r"(?:^|\s)\d{1,2}\.\s+(.*?)(?=\s+\d{1,2}\.\s+|$)",
            body,
            flags=re.I,
        )
        return [cls._clean(item) for item in matches if cls._clean(item)]

    @classmethod
    def _stable_title(cls, item: str) -> str:
        lowered = item.lower()
        if "cedars at cedar hills subdivision" in lowered and "plat j2" in lowered:
            return "The Cedars at Cedar Hills Subdivision Plat J2 Amendment"
        if "cedars townhomes" in lowered and "plat e" in lowered:
            return "The Cedars Townhomes Plat E Phase 5"
        if "canyon heights at cedar hills subdivision" in lowered and "plat m" in lowered:
            return "Canyon Heights at Cedar Hills Subdivision Plat M Amendment"

        text = cls._clean(item)
        text = re.sub(
            r"^Review/(?:Recommendation|Action)\s+and\s+Public Hearing\s+on\s+",
            "",
            text,
            flags=re.I,
        )
        return cls._clean(text)

    @staticmethod
    def _permit_type(item: str) -> str:
        lowered = item.lower()
        if "townhome" in lowered:
            return "Planning Townhome/Multifamily"
        if "site plan" in lowered:
            return "Planning Site Plan"
        if "development agreement" in lowered:
            return "Planning Development Agreement"
        if any(term in lowered for term in ("final plat", "preliminary plat", "preliminary plan", "subdivision", "plat ")):
            return "Planning Subdivision/Plat"
        if "rezone" in lowered or "rezoning" in lowered:
            return "Planning Rezone"
        if "annex" in lowered:
            return "Planning Annexation"
        return "Planning Review"

    @staticmethod
    def _units(item: str) -> int | None:
        match = re.search(r"\b(\d{1,4})\s+(?:lots|units)\b", item, flags=re.I)
        return int(match.group(1)) if match else None

    @classmethod
    def _address(cls, item: str) -> str:
        match = re.search(
            r"\b\d{2,5}\s+(?:North|South|East|West|N|S|E|W)\s+[A-Za-z0-9 .'-]+",
            item,
            flags=re.I,
        )
        return cls._clean(match.group(0)) if match else ""
