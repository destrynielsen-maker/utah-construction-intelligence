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
    "commercial",
    "development agreement",
    "final plat",
    "preliminary plat",
    "site plan",
    "subdivision",
    "townhome",
    "zone change",
    "rezone",
)

POLICY_ONLY_SIGNALS = (
    "accessory dwelling",
    "adu code",
    "development code",
    "fences, walls, and hedges",
    "sensitive land ordinance",
    "text amendment",
    "wildland-urban interface",
    "wui map",
    "zoning code",
)


class AlpineCollector:
    name = "Alpine"
    SCOPE_ID = "pmn-planning-development-v1"
    public_body_url = "https://www.utah.gov/pmn/sitemap/publicbody/866.html"
    notices_url = public_body_url
    MAX_NOTICE_PAGES = 10

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
            stable_key = permit.permit_number
            old = by_project.get(stable_key)
            if old is None or permit.issued_date > old.issued_date:
                by_project[stable_key] = permit

        permits = sorted(
            by_project.values(),
            key=lambda p: (p.issued_date, p.project_name or ""),
            reverse=True,
        )
        if not permits:
            detail = "; ".join(errors) if errors else "no project-specific Planning Commission items parsed"
            raise RuntimeError(f"Alpine planning source returned no usable records: {detail}")

        newest = max(p.issued_date for p in permits)
        note = (
            "Official Utah Public Notice Alpine Planning Commission agendas; "
            f"{len(permits)} project-specific development item(s), latest meeting {newest}; "
            "ADU/code/WUI/fence policy items excluded; planning/development-stage intelligence only"
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
            if "planning commission" not in text or "cancel" in text:
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
        if "cancelled" in text.lower() or "canceled" in text.lower():
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
                    permit_number=f"ALP-PLAN-{digest}",
                    issued_date=event_date,
                    permit_type=cls._permit_type(item),
                    address=cls._address(item),
                    project_name=title,
                    status="Planning Commission Agenda",
                    source_name="Utah Public Notice - Alpine Planning Commission",
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
        action_section = re.search(
            r"III\.\s+ACTION/DISCUSSION ITEMS:\s*(.*?)(?:\s+IV\.\s+COMMUNICATIONS|\s+V\.\s+APPROVAL|\s+ADJOURN|$)",
            description,
            flags=re.I,
        )
        body = action_section.group(1) if action_section else description
        matches = re.findall(
            r"(?:^|\s)[A-Z]\.\s+(?:Action Item:\s*|Discussion Item:\s*)?(.*?)(?=\s+[A-Z]\.\s+(?:Action Item:|Discussion Item:)|$)",
            body,
            flags=re.I,
        )
        return [cls._clean(item) for item in matches if cls._clean(item)]

    @classmethod
    def _stable_title(cls, item: str) -> str:
        lowered = item.lower()
        if "healey" in lowered and "subdivision" in lowered:
            return "Healey Blvd Subdivision Development Agreement"
        if "alpine fitness" in lowered:
            return "Alpine Fitness Commercial Site Plan"
        text = cls._clean(item)
        text = re.sub(r"^Public Hearing\s*-\s*", "", text, flags=re.I)
        text = re.sub(r"^Proposed\s+", "", text, flags=re.I)
        return cls._clean(text)

    @staticmethod
    def _permit_type(item: str) -> str:
        lowered = item.lower()
        if "site plan" in lowered:
            return "Planning Site Plan"
        if "development agreement" in lowered:
            return "Planning Development Agreement"
        if "final plat" in lowered or "preliminary plat" in lowered or "subdivision" in lowered:
            return "Planning Subdivision/Plat"
        if "rezone" in lowered or "zone change" in lowered:
            return "Planning Rezone"
        return "Planning Review"

    @classmethod
    def _address(cls, item: str) -> str:
        healey = re.search(r"\bHealey\s+Blvd\b", item, flags=re.I)
        if healey:
            return "Healey Blvd"
        match = re.search(
            r"\b\d{2,5}\s+(?:North|South|East|West|N|S|E|W)\s+[A-Za-z0-9 .'-]+",
            item,
            flags=re.I,
        )
        return cls._clean(match.group(0)) if match else ""
