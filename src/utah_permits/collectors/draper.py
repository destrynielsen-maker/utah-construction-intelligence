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
    "building",
    "conditional use",
    "development agreement",
    "land use map",
    "mixed use",
    "mixed-use",
    "office",
    "parking deviation",
    "plat amendment",
    "site plan",
    "subdivision",
    "warehouse",
    "zoning map",
)

POLICY_ONLY_SIGNALS = (
    "citywide",
    "code amendment",
    "development code amendment",
    "municipal code amendment",
    "ordinance amendment",
    "text amendment",
)


class DraperCollector:
    name = "Draper"
    SCOPE_ID = "pmn-planning-development-v1"
    public_body_url = "https://www.utah.gov/pmn/sitemap/publicbody/383.html"
    notices_url = public_body_url
    MAX_NOTICE_PAGES = 20

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
                permit = self.parse_notice_page(notice.text, notice.url)
                if permit:
                    permits.append(permit)
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
            detail = "; ".join(errors) if errors else "no project-specific Planning Commission notices parsed"
            raise RuntimeError(f"Draper planning source returned no usable records: {detail}")

        newest = max(p.issued_date for p in permits)
        note = (
            "Official Utah Public Notice Draper Planning Commission project notices; "
            f"{len(permits)} project-specific planning/development item(s), latest hearing {newest}; "
            "application numbers, addresses and project details retained when available; "
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
            if "cancel" in text:
                continue
            if not (
                "notice of public hearing" in text
                or "notice of public meeting" in text
                or "public hearing:" in text
            ):
                continue
            url = urljoin(source_url, href)
            if url not in seen:
                seen.add(url)
                found.append(url)
        return found

    @classmethod
    def parse_notice_page(cls, html: str, source_url: str) -> Permit | None:
        soup = BeautifulSoup(html, "html.parser")
        text = cls._clean(soup.get_text(" ", strip=True))
        lowered = text.lower()
        if "cancelled" in lowered or "canceled" in lowered:
            return None

        event_date = cls._event_date(text)
        description = cls._description(text)
        title = cls._notice_title(soup, text)
        if not event_date or not description or not title:
            return None

        combined = cls._clean(f"{title} {description}")
        normalized = combined.lower()
        if any(signal in normalized for signal in POLICY_ONLY_SIGNALS):
            return None
        if not any(signal in normalized for signal in DEVELOPMENT_SIGNALS):
            return None

        project_name = cls._stable_title(title)
        applications = cls._application_numbers(combined)
        stable = applications[0] if applications else hashlib.sha1(project_name.lower().encode("utf-8")).hexdigest()[:12].upper()

        return Permit(
            state="UT",
            jurisdiction=cls.name,
            permit_number=f"DRP-PLAN-{stable}",
            issued_date=event_date,
            permit_type=cls._permit_type(combined),
            address=cls._address(combined),
            project_name=project_name,
            units=cls._units(combined),
            area=cls._area(combined),
            status="Planning Commission Public Hearing/Meeting",
            source_name="Utah Public Notice - Draper Planning Commission",
            source_url=source_url,
            raw={
                "lead_stage": "PLANNING",
                "meeting_date": event_date,
                "date_semantics": "scheduled_planning_hearing_date",
                "application_numbers": applications,
                "notice_title": title,
                "description": description,
            },
        )

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
    def _notice_title(cls, soup: BeautifulSoup, text: str) -> str:
        heading = soup.find("h1")
        if heading:
            value = cls._clean(heading.get_text(" ", strip=True))
            if value and value.lower() not in {"utah.gov", "public notice website"}:
                return value
        match = re.search(
            r"(?:#\s*)?(Notice of Public (?:Hearing|Meeting):?\s+[^\n]+)",
            text,
            flags=re.I,
        )
        return cls._clean(match.group(1)) if match else ""

    @classmethod
    def _stable_title(cls, title: str) -> str:
        value = cls._clean(title)
        value = re.sub(r"^Notice of Public (?:Hearing|Meeting):\s*", "", value, flags=re.I)
        value = re.sub(r"^Public Hearing:\s*", "", value, flags=re.I)
        return cls._clean(value)

    @staticmethod
    def _application_numbers(value: str) -> list[str]:
        matches = re.findall(r"\b20\d{2}-\d{4}-[A-Z]{2,4}\b", value or "", flags=re.I)
        found: list[str] = []
        for match in matches:
            code = match.upper()
            if code not in found:
                found.append(code)
        return found

    @staticmethod
    def _permit_type(value: str) -> str:
        lowered = value.lower()
        if "site plan" in lowered:
            return "Planning Site Plan"
        if "parking deviation" in lowered:
            return "Planning Parking Deviation"
        if "plat amendment" in lowered or "subdivision" in lowered:
            return "Planning Subdivision/Plat"
        if "development agreement" in lowered:
            return "Planning Development Agreement"
        if "conditional use" in lowered:
            return "Planning Conditional Use"
        if "land use map" in lowered or "zoning map" in lowered:
            return "Planning Map Amendment"
        return "Planning Development Review"

    @classmethod
    def _address(cls, value: str) -> str:
        coordinate = re.search(
            r"\b\d{2,5}\s+(?:N|S|E|W|North|South|East|West)\.?\s+\d{1,5}\s+(?:N|S|E|W|North|South|East|West)\.?\b",
            value or "",
            flags=re.I,
        )
        if coordinate:
            return cls._clean(coordinate.group(0))
        street = re.search(
            r"\b\d{2,5}\s+(?:N|S|E|W|North|South|East|West)\.?\s+[A-Za-z][A-Za-z0-9 .'-]+?(?=,|\.|\s+Draper\b|$)",
            value or "",
            flags=re.I,
        )
        return cls._clean(street.group(0)) if street else ""

    @staticmethod
    def _units(value: str) -> int | None:
        match = re.search(r"\b(\d{1,4})\s+(?:lots|units)\b", value or "", flags=re.I)
        return int(match.group(1)) if match else None

    @staticmethod
    def _area(value: str) -> str | None:
        acres = re.search(r"\b(?:approximately\s+)?([\d.]+)\s+acres?\b", value or "", flags=re.I)
        if acres:
            return f"{acres.group(1)} acres"
        sqft = re.search(r"\b([\d,]+)\s*(?:square[- ]feet|sq\.?\s*ft\.?|square[- ]foot)\b", value or "", flags=re.I)
        if sqft:
            return f"{sqft.group(1)} sq ft"
        return None
