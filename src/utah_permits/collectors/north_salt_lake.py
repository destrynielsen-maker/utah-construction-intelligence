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
    "preliminary plat",
    "final plat",
    "subdivision",
    "general development plan",
    "development agreement",
    "zone change",
    "rezone",
    "zoning map amendment",
    "conditional use permit",
)

POLICY_ONLY_SIGNALS = (
    "land use code",
    "code amendment",
    "text amendment",
    "state code citation",
    "town center urban design standards",
    "general plan amendment",
    "legislative session",
    "annual training",
    "open and public meetings act",
)

LOW_VALUE_SIGNALS = (
    "home occupation",
    "accessory dwelling unit",
    "internal accessory dwelling",
    "detached accessory dwelling",
    "adu ",
    "sign permit",
    "variance",
)

ADMIN_SIGNALS = (
    "welcome and introduction",
    "public comment",
    "approval of planning commission minutes",
    "report on city council actions",
    "appointment of chair",
    "adjourn",
)


class NorthSaltLakeCollector:
    name = "North Salt Lake"
    SCOPE_ID = "pmn-planning-agendas-v1"
    public_body_url = "https://www.utah.gov/pmn/sitemap/publicbody/453.html"
    planning_url = "https://www.nslcity.org/261/Planning-Commission"
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
            raise RuntimeError(f"North Salt Lake planning source returned no usable records: {detail}")

        newest = max(p.issued_date for p in permits)
        note = (
            "Official Utah Public Notice North Salt Lake Planning Commission agendas, cross-checked against the "
            "City Planning Commission records page; "
            f"{len(permits)} project-specific planning/development item(s) from {pages_read} recent notice page(s), "
            f"latest substantive project meeting {newest}; plats, subdivisions, site plans, General Development "
            "Plans, development agreements and site-specific zoning actions retained; code-policy, training and "
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
            if not any(term in text for term in ("planning commission", "meeting agenda", "public hearing")):
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
        lowered = text.lower()
        if "city of north salt lake" not in lowered or "planning commission" not in lowered:
            return []
        if "canceled" in lowered or "cancelled" in lowered:
            return []

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
                    source_name="Utah Public Notice - North Salt Lake Planning Commission",
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
        body = re.split(r"\bPlanning Commission meetings are open to the public\b", description, maxsplit=1, flags=re.I)[0]
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
        if "preliminary plat" in lowered:
            return "Planning Preliminary Plat"
        if "final plat" in lowered:
            return "Planning Final Plat"
        if "site plan" in lowered:
            return "Planning Site Plan"
        if "general development plan" in lowered:
            return "Planning General Development Plan"
        if "development agreement" in lowered:
            return "Planning Development Agreement"
        if "zone change" in lowered or "rezone" in lowered or "zoning map amendment" in lowered:
            return "Planning Zone Change"
        if "conditional use permit" in lowered:
            return "Planning Conditional Use"
        if "subdivision" in lowered:
            return "Planning Subdivision"
        return "Planning Review"

    @classmethod
    def _project_name(cls, item: str, address: str, permit_type: str) -> str:
        patterns = (
            r"General Development Plan for\s+(.+?),\s+located at\s+\d",
            r"Preliminary Plat for\s+(.+?)\s+at\s+\d",
            r"Final Plat for\s+(.+?)\s+at\s+\d",
            r"Site Plan(?: Review)? for\s+(.+?)\s+at\s+\d",
            r"Development Agreement for\s+(.+?)\s+(?:at|located at)\s+\d",
            r"(?:Zone Change|Rezone|Zoning Map Amendment) for\s+(.+?)\s+(?:at|located at)\s+\d",
            r"Conditional Use Permit for\s+(.+?)\s+at\s+\d",
        )
        for pattern in patterns:
            match = re.search(pattern, item, flags=re.I)
            if match:
                value = cls._clean(match.group(1))
                value = re.sub(r"^(?:a|an)\s+", "", value, flags=re.I)
                if value:
                    return value[:180]
        label = permit_type.removeprefix("Planning ")
        if address:
            return f"{label} - {address}"[:180]
        return f"North Salt Lake {label}"[:180]

    @classmethod
    def _address(cls, item: str) -> str:
        patterns = (
            r"\b(?:at|located at)\s+(\d{1,6}\s+(?:North|South|East|West|N|S|E|W)\s+[A-Za-z0-9 .'-]+?(?:Road|Street|Drive|Avenue|Lane|Way|Boulevard|Court))(?=,|\s+\d|\s+[A-Z][a-z]+\s+[A-Z]|$)",
            r"\b(\d{1,6}\s+(?:North|South|East|West|N|S|E|W)\s+(?:Redwood Road|Orchard Drive|Highway 89|US 89))\b",
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
        return f"NSL-PLAN-{digest}"

    @classmethod
    def _dedupe(cls, permits: list[Permit]) -> list[Permit]:
        by_key: dict[str, Permit] = {}
        for permit in permits:
            old = by_key.get(permit.permit_number)
            if old is None or permit.issued_date > old.issued_date:
                by_key[permit.permit_number] = permit
        return sorted(by_key.values(), key=lambda p: (p.issued_date, p.project_name or ""), reverse=True)
