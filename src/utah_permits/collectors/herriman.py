from __future__ import annotations

import re
from datetime import datetime
from urllib.parse import urljoin

import requests
from bs4 import BeautifulSoup

from .base import CollectionResult, new_session
from ..models import Permit


DEVELOPMENT_SIGNALS = (
    "subdivision",
    "site plan",
    "conditional use",
    "rezone",
    "zoning amendment",
    "development agreement",
    "master development agreement",
    "general plan",
    "dwelling units",
)

POLICY_ONLY_SIGNALS = (
    "land development code",
    "title 10",
    "city code",
    "accessory dwelling",
    "adu",
    "statutory references",
    "clerical",
    "cross-reference",
)

LOW_VALUE_SIGNALS = (
    "monument sign",
    "sign permit",
)


class HerrimanCollector:
    name = "Herriman"
    SCOPE_ID = "pmn-planning-agendas-v1"
    public_body_url = "https://www.utah.gov/pmn/sitemap/publicbody/1151.html"
    notices_url = public_body_url
    MAX_NOTICE_PAGES = 8

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

        by_file: dict[str, Permit] = {}
        for permit in permits:
            old = by_file.get(permit.permit_number)
            if old is None or permit.issued_date > old.issued_date:
                by_file[permit.permit_number] = permit

        permits = sorted(
            by_file.values(),
            key=lambda p: (p.issued_date, p.project_name or ""),
            reverse=True,
        )
        if not permits:
            detail = "; ".join(errors) if errors else "no project-specific agenda items parsed"
            raise RuntimeError(f"Herriman planning source returned no usable records: {detail}")

        newest = max(p.issued_date for p in permits)
        note = (
            "Official Utah Public Notice Herriman Planning Commission agendas; "
            f"{len(permits)} project-specific planning/development item(s), latest meeting {newest}; "
            "file numbers, addresses, unit/lot counts and acreage retained when available; "
            "citywide code-policy and sign-only items excluded; planning/development-stage intelligence only"
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
            if "planning comm" not in text:
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
        for file_number, item in cls._agenda_items(description):
            normalized = item.lower()
            if not any(signal in normalized for signal in DEVELOPMENT_SIGNALS):
                continue
            if any(signal in normalized for signal in LOW_VALUE_SIGNALS):
                continue
            if any(signal in normalized for signal in POLICY_ONLY_SIGNALS):
                if "located" not in normalized and "property" not in normalized:
                    continue
            if "applicant: herriman city" in normalized and any(
                signal in normalized for signal in POLICY_ONLY_SIGNALS
            ):
                continue

            permits.append(
                Permit(
                    state="UT",
                    jurisdiction=cls.name,
                    permit_number=f"HER-PLAN-{file_number}",
                    issued_date=event_date,
                    permit_type=cls._permit_type(file_number, item),
                    address=cls._address(item),
                    project_name=cls._project_name(item),
                    units=cls._units(item),
                    status="Planning Commission Agenda Item",
                    source_name="Utah Public Notice - Herriman Planning Commission",
                    source_url=source_url,
                    raw={
                        "lead_stage": "PLANNING",
                        "meeting_date": event_date,
                        "date_semantics": "planning_commission_meeting_date",
                        "file_number": file_number,
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
    def _agenda_items(cls, description: str) -> list[tuple[str, str]]:
        matches = re.finditer(
            r"\b\d+\.\d+\.\s+(.*?)(?:\s+File No:\s*([A-Z]\d{4}-\d+))",
            description,
            flags=re.I,
        )
        return [(m.group(2).upper(), cls._clean(m.group(1))) for m in matches]

    @classmethod
    def _project_name(cls, item: str) -> str:
        named = re.search(r"\bfor\s+([A-Z][A-Za-z0-9 '&.-]+?),\s+located\b", item)
        if named:
            return cls._clean(named.group(1))

        address = cls._address(item)
        lowered = item.lower()
        if address:
            if "commercial restaurant" in lowered:
                return f"Commercial Restaurant Site Plan - {address}"
            if "preliminary subdivision" in lowered:
                return f"Preliminary Subdivision - {address}"
            if "site plan" in lowered:
                return f"Site Plan - {address}"
            if "rezone" in lowered or "zoning amendment" in lowered:
                return f"Rezone - {address}"
            if "development agreement" in lowered:
                return f"Development Agreement - {address}"

        short = re.split(r"\s+Applicant:\s*", item, maxsplit=1, flags=re.I)[0]
        short = re.sub(
            r"^(?:Review and consider|Consideration of|Review and consider approval of|Review and consider a recommendation to)\s+",
            "",
            short,
            flags=re.I,
        )
        return cls._clean(short)[:180]

    @staticmethod
    def _permit_type(file_number: str, item: str) -> str:
        lowered = item.lower()
        if file_number.startswith("S") or "subdivision" in lowered:
            return "Planning Subdivision/Plat"
        if file_number.startswith("P") or "site plan" in lowered:
            return "Planning Site Plan"
        if file_number.startswith("C") or "conditional use" in lowered:
            return "Planning Conditional Use"
        if file_number.startswith("Z") or "rezone" in lowered or "zoning amendment" in lowered:
            return "Planning Rezone"
        if "development agreement" in lowered:
            return "Planning Development Agreement"
        if "general plan" in lowered:
            return "Planning General Plan Amendment"
        return "Planning Review"

    @classmethod
    def _address(cls, item: str) -> str:
        match = re.search(
            r"\b\d{2,5}\s+(?:W|E|N|S)\.?\s+[A-Za-z0-9 .'-]+?(?=\s+in\s+the\b|,\s+in\s+the\b|\.\s|,\s+Applicant:|\s+Applicant:|$)",
            item,
            flags=re.I,
        )
        if match:
            return cls._clean(match.group(0).rstrip(","))
        return ""

    @staticmethod
    def _units(item: str) -> int | None:
        for pattern in (
            r"\bone\s+\((\d+)\)\s+lot\b",
            r"\b(\d{1,4})\s+(?:residential\s+)?dwelling units\b",
            r"\b(\d{1,4})[- ]lot\b",
            r"\b(\d{1,4})\s+lots\b",
        ):
            match = re.search(pattern, item, flags=re.I)
            if match:
                return int(match.group(1))
        return None

    @staticmethod
    def _acreage(item: str) -> float | None:
        match = re.search(r"Acres?:\s*\(\+/-\)?\s*([0-9.]+)", item, flags=re.I)
        if not match:
            match = re.search(r"Acres?:\s*([0-9.]+)", item, flags=re.I)
        if not match:
            return None
        try:
            return float(match.group(1))
        except ValueError:
            return None
