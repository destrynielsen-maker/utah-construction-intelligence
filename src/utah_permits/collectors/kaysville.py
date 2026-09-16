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
    "rezone",
    "rezoning",
    "zone change",
    "subdivision",
    "preliminary plat",
    "final plat",
    "site plan",
    "development agreement",
    "development plan",
)

POLICY_ONLY_SIGNALS = (
    "text amendment",
    "land use code",
    "city code",
    "planning commission bylaws",
    "political sign",
    "ordinance amendment",
    "general plan amendment",
)

LOW_VALUE_SIGNALS = (
    "home occupation",
    "electronic message center",
    "temporary merchant",
    "sign permit",
    "variance request",
)

ADMIN_SIGNALS = (
    "welcome",
    "conflict of interest",
    "approval of minutes",
    "approve minutes",
    "meeting minutes",
    "commission reports",
    "staff reports",
    "other matters",
    "adjourn",
    "elect chair",
    "vice chair",
)


class KaysvilleCollector:
    name = "Kaysville"
    SCOPE_ID = "pmn-planning-development-v1"
    public_body_url = "https://www.utah.gov/pmn/sitemap/publicbody/1546.html"
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

        permits = self._dedupe(permits)
        if not permits:
            detail = "; ".join(errors) if errors else "no project-specific planning items parsed"
            raise RuntimeError(f"Kaysville planning source returned no usable records: {detail}")

        newest = max(p.issued_date for p in permits)
        note = (
            "Official Utah Public Notice Kaysville Planning Commission notices; "
            f"{len(permits)} project-specific planning/development item(s), latest meeting/hearing {newest}; "
            "rezones, subdivisions and other site-specific development actions retained; home occupations, signs, "
            "citywide policy and administrative items excluded; planning/development-stage intelligence only"
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
            if "cancel" in text or "minutes" in text:
                continue
            if "planning commission" not in text and "public hearing" not in text:
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
        if "notice of cancellation" in lowered or "meeting cancelled" in lowered or "meeting canceled" in lowered:
            return []

        event_date = cls._event_date(text)
        description = cls._description(text)
        if not event_date or not description:
            return []

        items = cls._numbered_items(description)
        if not items and cls._keep_item(description):
            items = [description]

        permits: list[Permit] = []
        seen: set[str] = set()
        for item in items:
            item = cls._clean(item)
            if not cls._keep_item(item):
                continue

            permit_type = cls._permit_type(item)
            address = cls._address(item)
            apn = cls._parcel(item)
            project_name = cls._project_name(item, address, permit_type)
            permit_number = cls._stable_id(project_name, address, apn, permit_type)
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
                    apn=apn,
                    status="Planning Commission Agenda/Hearing Item",
                    source_name="Utah Public Notice - Kaysville Planning Commission",
                    source_url=source_url,
                    raw={
                        "lead_stage": "PLANNING",
                        "activity_date": event_date,
                        "date_semantics": "planning_commission_meeting_or_hearing_date",
                        "acreage": cls._acreage(item),
                        "agenda_item": item,
                    },
                )
            )
        return permits

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
    def _numbered_items(cls, description: str) -> list[str]:
        body = re.split(r"\b(?:ADJOURNMENT|ADJOURN)\b", description, maxsplit=1, flags=re.I)[0]
        matches = re.finditer(
            r"(?:^|\s)(\d+)\.\s+(.*?)(?=\s+\d+\.\s+|$)",
            body,
            flags=re.I,
        )
        return [cls._clean(m.group(2)) for m in matches]

    @staticmethod
    def _permit_type(item: str) -> str:
        lowered = item.lower()
        if "preliminary plat" in lowered:
            return "Planning Preliminary Plat"
        if "final plat" in lowered:
            return "Planning Final Plat"
        if "subdivision" in lowered:
            return "Planning Subdivision"
        if "site plan" in lowered:
            return "Planning Site Plan"
        if "development agreement" in lowered or "development plan" in lowered:
            return "Planning Development Review"
        if "rezone" in lowered or "rezoning" in lowered or "zone change" in lowered:
            return "Planning Rezone"
        return "Planning Review"

    @classmethod
    def _project_name(cls, item: str, address: str, permit_type: str) -> str:
        named = re.search(
            r"\b([A-Z][A-Za-z0-9'&.-]*(?:\s+[A-Z][A-Za-z0-9'&.-]*){0,5}\s+(?:Subdivision|Townhomes?|Apartments?|Development|Complex|Center|Estates?))\b",
            item,
        )
        if named:
            return cls._clean(named.group(1))[:180]
        label = permit_type.removeprefix("Planning ")
        if address:
            return f"{label} - {address}"[:180]
        parcel = cls._parcel(item)
        if parcel:
            return f"{label} - Parcel {parcel}"[:180]
        return f"Kaysville {label}"[:180]

    @classmethod
    def _address(cls, item: str) -> str:
        patterns = (
            r"(?:property\s+)?(?:located\s+)?at\s+(?:approximately\s+)?(\d{1,6}\s+[NSEW]?\s*[A-Za-z0-9][A-Za-z0-9 .'-]*(?:Street|St|Road|Rd|Lane|Ln|Drive|Dr|Circle|Ct|Court|Way|Avenue|Ave|Boulevard|Blvd))\b",
            r"(?:property is located at|located at)\s+(?:approximately\s+)?(.+?)(?=\s+(?:from|for|to)\b|[.;]|$)",
        )
        for pattern in patterns:
            match = re.search(pattern, item, flags=re.I)
            if match:
                return cls._clean(match.group(1))
        return ""

    @staticmethod
    def _parcel(item: str) -> str | None:
        match = re.search(r"\b(?:parcel(?:\s+number)?|parcel #)\s*[:#]?\s*([0-9]{2}-[0-9]{3}-[0-9]{4})\b", item, flags=re.I)
        return match.group(1) if match else None

    @staticmethod
    def _acreage(item: str) -> float | None:
        match = re.search(r"(?:approximately\s+)?([0-9.]+)\s+acres?\b", item, flags=re.I)
        if not match:
            return None
        try:
            return float(match.group(1))
        except ValueError:
            return None

    @classmethod
    def _stable_id(
        cls,
        project_name: str,
        address: str,
        apn: str | None,
        permit_type: str,
    ) -> str:
        seed = "|".join(
            part for part in (cls._clean(project_name).lower(), cls._clean(address).lower(), apn or "", permit_type.lower()) if part
        )
        digest = hashlib.sha1(seed.encode("utf-8")).hexdigest()[:12].upper()
        return f"KAY-PLAN-{digest}"

    @classmethod
    def _dedupe(cls, permits: list[Permit]) -> list[Permit]:
        by_key: dict[str, Permit] = {}
        for permit in permits:
            old = by_key.get(permit.permit_number)
            if old is None or cls._richness(permit) > cls._richness(old) or (
                cls._richness(permit) == cls._richness(old) and permit.issued_date > old.issued_date
            ):
                by_key[permit.permit_number] = permit
        return sorted(by_key.values(), key=lambda p: (p.issued_date, p.project_name or ""), reverse=True)

    @staticmethod
    def _richness(permit: Permit) -> tuple[int, int, int, int]:
        return (
            int(bool(permit.address)),
            int(bool(permit.apn)),
            int(permit.raw.get("acreage") is not None),
            len(str(permit.raw.get("agenda_item") or "")),
        )
