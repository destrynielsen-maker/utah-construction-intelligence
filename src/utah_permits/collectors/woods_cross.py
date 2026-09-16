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
    "site plan",
    "conditional use permit",
    "subdivision",
    "preliminary plat",
    "final plat",
    "zone change",
    "rezone",
    "zoning map amendment",
    "development agreement",
    "development plan",
)

POLICY_ONLY_SIGNALS = (
    "code text amendment",
    "text amendment",
    "code amendment",
    "municipal code",
    "zoning ordinance",
    "business regulations",
    "business licensing",
    "transportation master plan",
    "general plan amendment",
)

LOW_VALUE_SIGNALS = (
    "home occupation",
    "accessory dwelling unit",
    "internal accessory dwelling",
    "detached accessory dwelling",
    "dadu",
    "adu ",
    "second driveway",
    "hard surface",
    "sign permit",
    "variance",
)

ADMIN_SIGNALS = (
    "pledge",
    "meeting minutes",
    "open session",
    "director's report",
    "directors report",
    "adjourn",
)


class WoodsCrossCollector:
    name = "Woods Cross"
    SCOPE_ID = "pmn-planning-agendas-v1"
    public_body_url = "https://www.utah.gov/pmn/sitemap/publicbody/1843.html"
    notices_url = public_body_url
    MAX_NOTICE_PAGES = 12

    def collect(self, session: requests.Session | None = None) -> CollectionResult:
        session = session or new_session()
        response = session.get(self.public_body_url, timeout=30)
        response.raise_for_status()
        notice_urls = self.discover_notice_urls(response.text, response.url)

        permits: list[Permit] = []
        errors: list[str] = []
        pages_read = 0
        for notice_url in notice_urls[: self.MAX_NOTICE_PAGES]:
            try:
                notice = session.get(notice_url, timeout=30)
                notice.raise_for_status()
                permits.extend(self.parse_notice_page(notice.text, notice.url))
                pages_read += 1
            except Exception as exc:
                errors.append(f"{type(exc).__name__}: {exc}")

        permits = self._dedupe(permits)
        if not permits:
            detail = "; ".join(errors) if errors else "no project-specific planning items parsed"
            raise RuntimeError(f"Woods Cross planning source returned no usable records: {detail}")

        newest = max(p.issued_date for p in permits)
        note = (
            "Official Utah Public Notice Woods Cross Planning Commission agendas; "
            f"{len(permits)} project-specific planning/development item(s) from {pages_read} recent notice page(s), "
            f"latest substantive project meeting {newest}; site plans, subdivisions, zone changes and non-home "
            "commercial/industrial conditional-use reviews retained; ADU, home-occupation, code-policy and "
            "administrative items excluded; planning/development-stage intelligence only"
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
            if "planning commission" not in text and "public hearing" not in text:
                continue
            if "cancel" in text or "meeting schedule" in text:
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
        event_date = cls._event_date(text)
        description = cls._description(text)
        if not event_date or not description:
            return []

        permits: list[Permit] = []
        seen: set[str] = set()
        for item in cls._numbered_items(description):
            if not cls._keep_item(item):
                continue
            permit_type = cls._permit_type(item)
            address = cls._address(item)
            project_name = cls._project_name(item, address, permit_type)
            permit_number = cls._stable_id(project_name, address, permit_type)
            if permit_number in seen:
                continue
            seen.add(permit_number)
            permits.append(
                Permit(
                    state="UT",
                    jurisdiction=cls.name,
                    permit_number=permit_number,
                    issued_date=event_date,
                    permit_type=permit_type,
                    address=address,
                    project_name=project_name,
                    status="Planning Commission Agenda Item",
                    source_name="Utah Public Notice - Woods Cross Planning Commission",
                    source_url=source_url,
                    raw={
                        "lead_stage": "PLANNING",
                        "activity_date": event_date,
                        "date_semantics": "planning_commission_meeting_date",
                        "agenda_item": item,
                    },
                )
            )
        return permits

    @classmethod
    def _numbered_items(cls, description: str) -> list[str]:
        body = re.split(r"\bNotice of Special Accommodations\b", description, maxsplit=1, flags=re.I)[0]
        matches = re.finditer(
            r"(?:^|\s)(\d{1,2})\.\s+(.*?)(?=\s+\d{1,2}\.\s+|$)",
            body,
            flags=re.I,
        )
        return [cls._clean(match.group(2)) for match in matches]

    @classmethod
    def _keep_item(cls, item: str) -> bool:
        lowered = item.lower()
        if any(signal in lowered for signal in ADMIN_SIGNALS):
            return False
        if any(signal in lowered for signal in POLICY_ONLY_SIGNALS):
            return False
        if any(signal in lowered for signal in LOW_VALUE_SIGNALS):
            return False
        return any(signal in lowered for signal in DEVELOPMENT_SIGNALS)

    @staticmethod
    def _permit_type(item: str) -> str:
        lowered = item.lower()
        if "site plan" in lowered:
            return "Planning Site Plan"
        if "preliminary plat" in lowered:
            return "Planning Preliminary Plat"
        if "final plat" in lowered:
            return "Planning Final Plat"
        if "subdivision" in lowered:
            return "Planning Subdivision"
        if "zone change" in lowered or "rezone" in lowered or "zoning map amendment" in lowered:
            return "Planning Zone Change"
        if "conditional use permit" in lowered:
            return "Planning Conditional Use"
        if "development agreement" in lowered or "development plan" in lowered:
            return "Planning Development Review"
        return "Planning Review"

    @classmethod
    def _project_name(cls, item: str, address: str, permit_type: str) -> str:
        patterns = (
            r"(?:Site Plan Review|Conditional Use Permit|Preliminary Plat|Final Plat|Subdivision|Zone Change|Rezone|Development Agreement)\s+(?:for\s+)?(?:a\s+|an\s+|the\s+)?(.+?)\s+at\s+\d",
            r"^(\d{1,6}\s+(?:North|South|East|West|N|S|E|W)\s+\d{1,6}\s+(?:North|South|East|West|N|S|E|W))\s+(.+?)(?:\s+Applicant:|\s+Presenter:|\s+-\s+Review|$)",
        )
        for pattern in patterns:
            match = re.search(pattern, item, flags=re.I)
            if not match:
                continue
            value = match.group(1) if len(match.groups()) == 1 else match.group(2)
            value = cls._clean(value)
            if value:
                return value[:180]
        label = permit_type.removeprefix("Planning ")
        if address:
            return f"{label} - {address}"[:180]
        return f"Woods Cross {label}"[:180]

    @classmethod
    def _address(cls, item: str) -> str:
        patterns = (
            r"\bat\s+(\d{1,6}\s+(?:North|South|East|West|N|S|E|W)\s+\d{1,6}\s+(?:North|South|East|West|N|S|E|W))(?:,\s*Suite\s+[A-Za-z0-9-]+)?\b",
            r"\b(\d{1,6}\s+(?:North|South|East|West|N|S|E|W)\s+\d{1,6}\s+(?:North|South|East|West|N|S|E|W))\s+(?:Zone Change|Rezone)\b",
        )
        for pattern in patterns:
            match = re.search(pattern, item, flags=re.I)
            if match:
                return cls._clean(match.group(1))
        return ""

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

    @staticmethod
    def _clean(value: str) -> str:
        return re.sub(r"\s+", " ", value or "").strip(" .")

    @classmethod
    def _stable_id(cls, project_name: str, address: str, permit_type: str) -> str:
        seed = "|".join(
            part for part in (cls._clean(project_name).lower(), cls._clean(address).lower(), permit_type.lower()) if part
        )
        digest = hashlib.sha1(seed.encode("utf-8")).hexdigest()[:12].upper()
        return f"WXC-PLAN-{digest}"

    @classmethod
    def _dedupe(cls, permits: list[Permit]) -> list[Permit]:
        by_key: dict[str, Permit] = {}
        for permit in permits:
            old = by_key.get(permit.permit_number)
            if old is None or permit.issued_date > old.issued_date:
                by_key[permit.permit_number] = permit
        return sorted(by_key.values(), key=lambda p: (p.issued_date, p.project_name or ""), reverse=True)
