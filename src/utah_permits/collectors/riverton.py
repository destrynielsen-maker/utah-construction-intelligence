from __future__ import annotations

import re
from datetime import datetime
from urllib.parse import urljoin

import requests
from bs4 import BeautifulSoup

from .base import CollectionResult, new_session
from ..models import Permit


POLICY_ONLY_SIGNALS = (
    "land use ordinance amendment",
    "city code",
    "title 18",
    "home occupation",
)

LOW_VALUE_SIGNALS = (
    "dumpster addition",
    "adding a dumpster",
)


class RivertonCollector:
    name = "Riverton"
    SCOPE_ID = "pmn-planning-agendas-v1"
    public_body_url = "https://www.utah.gov/pmn/sitemap/publicbody/5473.html"
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

        by_application: dict[str, Permit] = {}
        for permit in permits:
            old = by_application.get(permit.permit_number)
            if old is None or permit.issued_date > old.issued_date:
                by_application[permit.permit_number] = permit

        permits = sorted(
            by_application.values(),
            key=lambda p: (p.issued_date, p.project_name or ""),
            reverse=True,
        )
        if not permits:
            detail = "; ".join(errors) if errors else "no project-specific agenda items parsed"
            raise RuntimeError(f"Riverton planning source returned no usable records: {detail}")

        newest = max(p.issued_date for p in permits)
        note = (
            "Official Utah Public Notice Riverton Planning Commission agendas; "
            f"{len(permits)} project-specific planning/development item(s), latest meeting {newest}; "
            "application numbers, addresses, lot counts and acreage retained when available; "
            "home occupations, citywide code-policy and trivial site-plan changes excluded; "
            "planning/development-stage intelligence only"
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
            if "planning commission meeting" not in text:
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
        if "notice of cancellation" in lowered or "meeting cancelled" in lowered or "meeting canceled" in lowered:
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
            if any(signal in normalized for signal in LOW_VALUE_SIGNALS):
                continue

            application_numbers = cls._application_numbers(item)
            if not application_numbers:
                continue
            primary = application_numbers[0]

            permits.append(
                Permit(
                    state="UT",
                    jurisdiction=cls.name,
                    permit_number=f"RIV-PLAN-{primary}",
                    issued_date=event_date,
                    permit_type=cls._permit_type(item),
                    address=cls._address(item),
                    project_name=cls._project_name(item),
                    units=cls._units(item),
                    status="Planning Commission Agenda Item",
                    source_name="Utah Public Notice - Riverton Planning Commission",
                    source_url=source_url,
                    raw={
                        "lead_stage": "PLANNING",
                        "meeting_date": event_date,
                        "date_semantics": "planning_commission_meeting_date",
                        "application_numbers": application_numbers,
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
    def _agenda_items(cls, description: str) -> list[str]:
        matches = re.finditer(
            r"\b2\.[a-z]\s*[\'\"]?(.*?)(?=\s+2\.[a-z]\s|\s+3\.\s|$)",
            description,
            flags=re.I,
        )
        return [cls._clean(m.group(1)) for m in matches]

    @staticmethod
    def _application_numbers(item: str) -> list[str]:
        values = re.findall(r"\bPLZ-\d{2}-\d{4}\b", item, flags=re.I)
        return [v.upper() for v in values]

    @classmethod
    def _project_name(cls, item: str) -> str:
        quoted = re.match(r"[\'\"]?([^\'\"]+?)[\'\"]?,\s+PLZ-", item, flags=re.I)
        if quoted:
            return cls._clean(quoted.group(1))
        before_app = re.split(r"\s+PLZ-\d{2}-\d{4}", item, maxsplit=1, flags=re.I)[0]
        return cls._clean(before_app.strip("'\" ,"))[:180]

    @staticmethod
    def _permit_type(item: str) -> str:
        lowered = item.lower()
        if "commercial site plan" in lowered:
            return "Planning Commercial Site Plan"
        if "preliminary residential subdivision" in lowered or "subdivision" in lowered:
            return "Planning Subdivision/Plat"
        if "rezone" in lowered:
            return "Planning Rezone"
        if "conditional use" in lowered:
            return "Planning Conditional Use"
        if "site plan" in lowered:
            return "Planning Site Plan"
        return "Planning Review"

    @classmethod
    def _address(cls, item: str) -> str:
        match = re.search(
            r"(?:located at|located at approximately|to be located at)\s+(.+?)(?=\.\s|\. Applicant|,\s*Applicant|$)",
            item,
            flags=re.I,
        )
        if match:
            return cls._clean(match.group(1))
        return ""

    @staticmethod
    def _units(item: str) -> int | None:
        for pattern in (
            r"up to\s+(\d{1,4})\s+(?:residential\s+)?lots",
            r"\b(\d{1,4})[- ]lot\b",
            r"\b(\d{1,4})\s+(?:residential\s+)?lots\b",
        ):
            match = re.search(pattern, item, flags=re.I)
            if match:
                return int(match.group(1))
        return None

    @staticmethod
    def _acreage(item: str) -> float | None:
        match = re.search(r"(?:approximately\s+)?([0-9.]+)-acres?\b", item, flags=re.I)
        if not match:
            return None
        try:
            return float(match.group(1))
        except ValueError:
            return None
