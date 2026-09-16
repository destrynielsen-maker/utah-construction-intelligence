from __future__ import annotations

import hashlib
import re
from datetime import datetime
from urllib.parse import urljoin

import requests
from bs4 import BeautifulSoup

from .base import CollectionResult, new_session
from ..models import Permit


POLICY_ONLY_SIGNALS = (
    "accessory dwelling",
    "adu",
    "text amendment",
    "city code",
    "title 19",
    "planning application process",
    "regulations for murals",
)

LOW_VALUE_SIGNALS = (
    "home occupation",
    "neighborhood identification sign",
    "trail easement",
    "transfer approximately 114 square feet",
    "transferring 1,350 square feet",
    "transferring 1350 square feet",
    "533 square-foot",
    "533 square foot",
)

DEVELOPMENT_SIGNALS = (
    "preliminary plat",
    "subdivision",
    "rezone",
    "development plan",
    "site plan",
    "conditional use",
    "construction of a new",
    "facility expansion",
)


class LaytonCollector:
    name = "Layton"
    SCOPE_ID = "pmn-planning-agendas-hearings-v1"
    public_body_url = "https://www.utah.gov/pmn/sitemap/publicbody/316.html"
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
            raise RuntimeError(f"Layton planning source returned no usable records: {detail}")

        newest = max(p.issued_date for p in permits)
        note = (
            "Official Utah Public Notice Layton Planning Commission agendas and project hearings; "
            f"{len(permits)} project-specific planning/development item(s), latest meeting/hearing {newest}; "
            "addresses, lot/unit counts and acreage retained when available; home occupations, citywide code-policy "
            "and minor administrative plat changes excluded; planning/development-stage intelligence only"
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
            if not ("meeting agenda" in text or "public hearing" in text):
                continue
            if "cancel" in text:
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
        if "canceled meeting" in lowered or "cancelled meeting" in lowered or "notice of cancellation" in lowered:
            return []

        event_date = cls._event_date(text)
        description = cls._description(text)
        if not event_date or not description:
            return []
        if "planning commission" not in description.lower():
            return []

        items = cls._numbered_items(description)
        if not items and cls._is_project_hearing(description):
            items = [description]

        permits: list[Permit] = []
        for item in items:
            normalized = item.lower()
            if any(signal in normalized for signal in POLICY_ONLY_SIGNALS):
                continue
            if any(signal in normalized for signal in LOW_VALUE_SIGNALS):
                continue
            if not any(signal in normalized for signal in DEVELOPMENT_SIGNALS):
                continue

            project_name = cls._project_name(item)
            address = cls._address(item)
            permit_type = cls._permit_type(item)
            permit_number = cls._stable_id(project_name, address, permit_type)
            permits.append(
                Permit(
                    state="UT",
                    jurisdiction=cls.name,
                    permit_number=permit_number,
                    issued_date=event_date,
                    permit_type=permit_type,
                    address=address,
                    project_name=project_name,
                    units=cls._units(item),
                    status="Planning Commission Agenda/Hearing Item",
                    source_name="Utah Public Notice - Layton Planning Commission",
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
        starts = [m.start() for m in re.finditer(r"\b(?:PUBLIC MEETING|PUBLIC HEARING)\b", description, flags=re.I)]
        if not starts:
            return []
        body = description[min(starts) :]
        body = re.split(r"\bADJOURNMENT\b", body, maxsplit=1, flags=re.I)[0]
        matches = re.finditer(
            r"(?:^|\s)(\d+)\.\s+(.*?)(?=\s+\d+\.\s+|$)",
            body,
            flags=re.I,
        )
        return [cls._clean(m.group(2)) for m in matches]

    @staticmethod
    def _is_project_hearing(description: str) -> bool:
        lowered = description.lower()
        return (
            "public hearing" in lowered
            and "planning commission" in lowered
            and any(signal in lowered for signal in ("proposal to rezone", "subdivision", "site plan", "development"))
        )

    @classmethod
    def _project_name(cls, item: str) -> str:
        first = re.split(
            r"\s+-\s+(?:PRELIMINARY PLAT|PLAT AMENDMENT|DEVELOPMENT PLAN AMENDMENT|REZONE|SITE PLAN|CONDITIONAL USE)\b",
            item,
            maxsplit=1,
            flags=re.I,
        )[0]
        first = cls._clean(first)
        if first and not first.lower().startswith(("notice of", "public notice")):
            return first[:180]

        address = cls._address(item)
        lowered = item.lower()
        if "rezone" in lowered:
            return f"Rezone - {address}" if address else "Layton Planning Rezone"
        if "subdivision" in lowered:
            return f"Subdivision - {address}" if address else "Layton Planning Subdivision"
        if "site plan" in lowered:
            return f"Site Plan - {address}" if address else "Layton Planning Site Plan"
        return (address or "Layton Planning Project")[:180]

    @staticmethod
    def _permit_type(item: str) -> str:
        lowered = item.lower()
        if "preliminary plat" in lowered or "subdivision" in lowered:
            return "Planning Subdivision/Plat"
        if "development plan" in lowered:
            return "Planning Development Plan Amendment"
        if "rezone" in lowered:
            return "Planning Rezone"
        if "site plan" in lowered:
            return "Planning Site Plan"
        if "conditional use" in lowered:
            return "Planning Conditional Use"
        return "Planning Review"

    @classmethod
    def _address(cls, item: str) -> str:
        patterns = (
            r"(?:property is located at|located at)\s+(?:approximately\s+)?(.+?)(?=\.\s|\.?$)",
            r"property\s+located\s+at\s+(?:approximately\s+)?(.+?)(?=\.\s|\.?$)",
        )
        for pattern in patterns:
            match = re.search(pattern, item, flags=re.I)
            if match:
                return cls._clean(match.group(1))
        return ""

    @staticmethod
    def _units(item: str) -> int | None:
        patterns = (
            r"\b(\d{1,4})\s+single-family lots\b",
            r"\b(\d{1,4})[- ]unit\s+townhome\b",
            r"\b(\d{1,4})\s+(?:residential\s+)?lots\b",
            r"\b(\d{1,4})\s+units\b",
            r"\ba one-lot subdivision\b",
        )
        for pattern in patterns:
            match = re.search(pattern, item, flags=re.I)
            if match:
                if match.groups():
                    return int(match.group(1))
                return 1
        return None

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
    def _stable_id(cls, project_name: str, address: str, permit_type: str) -> str:
        seed = cls._clean(project_name).lower() or cls._clean(address).lower() or permit_type.lower()
        digest = hashlib.sha1(seed.encode("utf-8")).hexdigest()[:12].upper()
        return f"LAY-PLAN-{digest}"

    @classmethod
    def _dedupe(cls, permits: list[Permit]) -> list[Permit]:
        by_name: dict[str, Permit] = {}
        for permit in permits:
            key = cls._clean(permit.project_name or "").lower()
            old = by_name.get(key)
            if old is None or cls._richness(permit) > cls._richness(old) or (
                cls._richness(permit) == cls._richness(old) and permit.issued_date > old.issued_date
            ):
                by_name[key] = permit

        by_address: dict[str, Permit] = {}
        no_address: list[Permit] = []
        for permit in by_name.values():
            address = cls._clean(permit.address).lower()
            if not address:
                no_address.append(permit)
                continue
            old = by_address.get(address)
            if old is None or cls._richness(permit) > cls._richness(old) or (
                cls._richness(permit) == cls._richness(old) and permit.issued_date > old.issued_date
            ):
                by_address[address] = permit

        combined = list(by_address.values()) + no_address
        return sorted(combined, key=lambda p: (p.issued_date, p.project_name or ""), reverse=True)

    @staticmethod
    def _richness(permit: Permit) -> tuple[int, int, int, int]:
        return (
            int(bool(permit.address)),
            int(permit.units is not None),
            int(permit.raw.get("acreage") is not None),
            len(str(permit.raw.get("agenda_item") or "")),
        )
