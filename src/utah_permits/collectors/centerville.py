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
    "subdivision",
    "preliminary plat",
    "final plat",
    "rezone",
    "rezoning",
    "zoning map amendment",
    "development agreement",
    "development plan",
)

POLICY_ONLY_SIGNALS = (
    "code amendment",
    "code amendments",
    "municipal code amendment",
    "municipal code amendments",
    "zoning code amendment",
    "zoning code amendments",
    "detached accessory dwelling",
    "dadu",
    "boundary line adjustment",
    "boundary establishment",
    "exchange of title",
    "historic preservation commission",
    "parkstrips",
    "landscaping and screening",
)

LOW_VALUE_SIGNALS = (
    "home occupation",
    "waiver of strict compliance for landscaping",
    "landscaping waiver",
    "sign permit",
    "temporary use",
)

ADMIN_SIGNALS = (
    "roll call",
    "prayer or thought",
    "pledge of allegiance",
    "community development director's report",
    "community development directors report",
    "minutes review and approval",
    "planning commission elections",
    "chairperson and vice chairperson",
    "adjournment",
    "certificate of posting",
)


class CentervilleCollector:
    name = "Centerville"
    SCOPE_ID = "pmn-planning-development-v1"
    public_body_url = "https://www.utah.gov/pmn/sitemap/publicbody/446.html"
    notices_url = public_body_url
    MAX_NOTICE_PAGES = 14

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
            raise RuntimeError(f"Centerville planning source returned no usable records: {detail}")

        newest = max(p.issued_date for p in permits)
        note = (
            "Official Utah Public Notice Centerville Planning Commission notices; "
            f"{len(permits)} project-specific planning/development item(s), latest substantive project meeting/hearing {newest}; "
            "site-plan, subdivision, rezone and other site-specific development actions retained; code-only, DADU, "
            "home-occupation, landscaping-waiver and administrative items excluded; planning/development-stage intelligence only"
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
            if "cancel" in text or "meeting schedule" in text:
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
        if "meeting has been cancelled" in lowered or "meeting has been canceled" in lowered or "notice of cancellation" in lowered:
            return []

        event_date = cls._event_date(text)
        description = cls._description(text)
        if not event_date or not description:
            return []

        items = cls._business_items(description)
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
                    source_name="Utah Public Notice - Centerville Planning Commission",
                    source_url=source_url,
                    raw={
                        "lead_stage": "PLANNING",
                        "activity_date": event_date,
                        "date_semantics": "planning_commission_meeting_or_hearing_date",
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
    def _business_items(cls, description: str) -> list[str]:
        business = re.search(
            r"\bB\.\s*BUSINESS ITEMS\b(.*?)(?:\bC\.\s*COMMUNITY DEVELOPMENT|\bD\.\s*MINUTES|\bE\.\s*ADJOURNMENT|$)",
            description,
            flags=re.I,
        )
        body = business.group(1) if business else description
        matches = re.finditer(
            r"(?:^|\s)(\d+)\.\s+(.*?)(?=\s+\d+\.\s+|$)",
            body,
            flags=re.I,
        )
        return [cls._clean(m.group(2)) for m in matches]

    @staticmethod
    def _permit_type(item: str) -> str:
        lowered = item.lower()
        if "final site plan amendment" in lowered:
            return "Planning Final Site Plan Amendment"
        if "site plan amendment" in lowered:
            return "Planning Site Plan Amendment"
        if "site plan" in lowered:
            return "Planning Site Plan"
        if "preliminary plat" in lowered:
            return "Planning Preliminary Plat"
        if "final plat" in lowered:
            return "Planning Final Plat"
        if "subdivision" in lowered:
            return "Planning Subdivision"
        if "zoning map amendment" in lowered or "rezone" in lowered or "rezoning" in lowered:
            return "Planning Rezone"
        if "development agreement" in lowered or "development plan" in lowered:
            return "Planning Development Review"
        return "Planning Review"

    @classmethod
    def _project_name(cls, item: str, address: str, permit_type: str) -> str:
        title = re.search(
            r"(?:Public Hearing\s*-\s*)?(?:Final\s+)?(?:Site Plan Amendment|Site Plan|Preliminary Plat|Final Plat|Subdivision|Rezone|Zoning Map Amendment|Development Agreement)\s*-\s*([^–—-]+?)(?=\s+-\s+\d|\s+-\s+(?:Commercial|Industrial|Residential|Administrative|Legislative)|$)",
            item,
            flags=re.I,
        )
        if title:
            value = cls._clean(title.group(1))
            if value:
                return value[:180]
        named = re.search(
            r"\b([A-Z][A-Za-z0-9'&.-]*(?:\s+[A-Z][A-Za-z0-9'&.-]*){0,5}\s+(?:Subdivision|Development|Fabrication|Steelworks|Pastures|Estates?))\b",
            item,
        )
        if named:
            return cls._clean(named.group(1))[:180]
        label = permit_type.removeprefix("Planning ")
        if address:
            return f"{label} - {address}"[:180]
        if apn := cls._parcel(item):
            return f"{label} - Parcel {apn}"[:180]
        return f"Centerville {label}"[:180]

    @classmethod
    def _address(cls, item: str) -> str:
        patterns = (
            r"located at approximately\s+(.+?)(?=,|\s+-\s+|\.|$)",
            r"commercial property located at approximately\s+(.+?)(?=,|\.|$)",
            r"(?:Site Plan Amendment|Site Plan|Preliminary Plat|Final Plat|Subdivision|Rezone|Development Agreement)\s*-\s*[^–—-]+?\s+-\s+(\d{1,6}\s+[NSEW]?\s*[A-Za-z0-9][A-Za-z0-9 .'-]*(?:Street|St|Road|Rd|Lane|Ln|Drive|Dr|Court|Ct|Circle|Way|Avenue|Ave|North|South|East|West))(?=\s+-|\s*,|$)",
        )
        for pattern in patterns:
            match = re.search(pattern, item, flags=re.I)
            if match:
                return cls._clean(match.group(1))
        return ""

    @staticmethod
    def _parcel(item: str) -> str | None:
        match = re.search(r"\bparcel(?:\s+number)?\s*[:#]?\s*([0-9]{2}-[0-9]{3}-[0-9]{4})\b", item, flags=re.I)
        return match.group(1) if match else None

    @classmethod
    def _stable_id(cls, project_name: str, address: str, apn: str | None, permit_type: str) -> str:
        seed = "|".join(
            part for part in (cls._clean(project_name).lower(), cls._clean(address).lower(), apn or "", permit_type.lower()) if part
        )
        digest = hashlib.sha1(seed.encode("utf-8")).hexdigest()[:12].upper()
        return f"CEN-PLAN-{digest}"

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
    def _richness(permit: Permit) -> tuple[int, int, int]:
        return (
            int(bool(permit.address)),
            int(bool(permit.apn)),
            len(str(permit.raw.get("agenda_item") or "")),
        )
