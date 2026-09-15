from __future__ import annotations

import hashlib
import re
from datetime import datetime
from urllib.parse import urljoin

import requests
from bs4 import BeautifulSoup

from .base import CollectionResult, new_session
from ..models import Permit


PROJECT_NOTICE_SIGNALS = (
    "notice of public meeting",
    "notice of public hearing",
)

DEVELOPMENT_SIGNALS = (
    "subdivision",
    "site plan",
    "preliminary plat",
    "final subdivision",
    "special exception",
    "rezone",
    "rezoning",
    "townhome",
    "single-family",
    "single family",
    "residential lot",
)

POLICY_ONLY_SIGNALS = (
    "accessory dwelling",
    "adu",
    "code amendment",
    "land development code",
    "ordinance amendment",
)


class SandyCollector:
    name = "Sandy"
    SCOPE_ID = "pmn-project-notices-v1"
    public_body_url = "https://www.utah.gov/pmn/sitemap/publicbody/466.html"
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
            detail = "; ".join(errors) if errors else "no project-specific notices parsed"
            raise RuntimeError(f"Sandy planning source returned no usable records: {detail}")

        newest = max(p.issued_date for p in permits)
        note = (
            "Official Utah Public Notice Sandy Planning Commission project notices; "
            f"{len(permits)} project-specific planning/development item(s), latest meeting {newest}; "
            "generic meetings and ADU/code-amendment notices excluded; planning/development-stage intelligence only"
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
            if "/pmn/sitemap/notice/" not in href and "/pmn/sitemap/noticehistory/" not in href:
                continue
            text = cls._clean(" ".join(anchor.stripped_strings)).lower()
            if not any(signal in text for signal in PROJECT_NOTICE_SIGNALS):
                continue
            if "cancel" in text or any(signal in text for signal in POLICY_ONLY_SIGNALS):
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

        normalized = description.lower()
        if any(signal in normalized for signal in POLICY_ONLY_SIGNALS):
            return []
        if not any(signal in normalized for signal in DEVELOPMENT_SIGNALS):
            return []

        title = cls._stable_title(text, description)
        application_number = cls._application_number(description)
        stable = application_number or title
        digest = hashlib.sha1(stable.lower().encode("utf-8")).hexdigest()[:12].upper()
        permit_number = f"SAN-PLAN-{application_number or digest}"

        return [
            Permit(
                state="UT",
                jurisdiction=cls.name,
                permit_number=permit_number,
                issued_date=event_date,
                permit_type=cls._permit_type(description),
                address=cls._address(description),
                project_name=title,
                units=cls._units(description),
                status="Planning Commission/Public Meeting Notice",
                source_name="Utah Public Notice - Sandy Planning Commission",
                source_url=source_url,
                raw={
                    "lead_stage": "PLANNING",
                    "meeting_date": event_date,
                    "date_semantics": "scheduled_public_meeting_or_hearing_date",
                    "application_number": application_number,
                    "notice_text": description,
                },
            )
        ]

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
    def _stable_title(cls, full_text: str, description: str) -> str:
        known = (
            ("liberty drug", "Liberty Drug Site Plan/Subdivision"),
            ("indigo subdivision", "Indigo Subdivision"),
            ("mountain side baptist", "Mountain Side Baptist Church Site Plan/Subdivision"),
            ("pharm 106", "Pharm 106 Subdivision"),
            ("raddon summit", "Raddon Summit Subdivision"),
            ("hagan road", "Hagan Road Rezone"),
        )
        lowered = f"{full_text} {description}".lower()
        for signal, title in known:
            if signal in lowered:
                return title

        if "830 e 9400 s" in lowered and "subdivision" in lowered:
            return "830 E 9400 S Final Subdivision Amendment"

        request = re.search(
            r"regarding\s+(?:a|an)\s+(.+?)(?:\s+submitted by|\s+for the property|\s+on the property|\.|$)",
            description,
            flags=re.I,
        )
        if request:
            return cls._clean(request.group(1)).title()
        return cls._clean(description)[:180]

    @staticmethod
    def _application_number(value: str) -> str | None:
        match = re.search(
            r"\b(?:SUB|SPR|SPX|REZ)[A-Z0-9-]{5,}\b",
            value,
            flags=re.I,
        )
        return match.group(0).upper() if match else None

    @staticmethod
    def _permit_type(value: str) -> str:
        lowered = value.lower()
        if "rezone" in lowered or "rezoning" in lowered:
            return "Planning Rezone"
        if "site plan" in lowered and "subdivision" in lowered:
            return "Planning Site Plan/Subdivision"
        if "site plan" in lowered:
            return "Planning Site Plan"
        if "final subdivision" in lowered or "preliminary plat" in lowered or "subdivision" in lowered:
            return "Planning Subdivision/Plat"
        if "special exception" in lowered:
            return "Planning Special Exception"
        return "Planning Review"

    @staticmethod
    def _units(value: str) -> int | None:
        for pattern in (
            r"\b(\d{1,4})-lot\b",
            r"\b(\d{1,4})\s+(?:residential\s+)?lots\b",
            r"\b(\d{1,4})\s+townhome\s+properties\b",
        ):
            match = re.search(pattern, value, flags=re.I)
            if match:
                return int(match.group(1))
        return None

    @classmethod
    def _address(cls, value: str) -> str:
        match = re.search(
            r"\b\d{2,5}\s+(?:E(?:ast)?|W(?:est)?|N(?:orth)?|S(?:outh)?)\.?\s+[A-Za-z0-9 .'-]+?(?=\.|,|\s+\[|\s+The request|\s+on the property|$)",
            value,
            flags=re.I,
        )
        return cls._clean(match.group(0)) if match else ""
