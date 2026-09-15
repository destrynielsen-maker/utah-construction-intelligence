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
    "annex",
    "conditional use",
    "development agreement",
    "final plat",
    "mixed use",
    "mixed-use",
    "multifamily",
    "office",
    "preliminary plat",
    "rezone",
    "rezoning",
    "site plan",
    "subdivision",
    "townhome",
)

POLICY_ONLY_SIGNALS = (
    "code amendment",
    "municipal code",
    "senate bill",
    "ordinance 2026-11",
    "plat signature requirements",
)


class VineyardCollector:
    name = "Vineyard"
    SCOPE_ID = "pmn-planning-agendas-v1"
    public_body_url = "https://www.utah.gov/pmn/sitemap/publicbody/531.html"
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

        by_key = {permit.key: permit for permit in permits}
        permits = sorted(
            by_key.values(),
            key=lambda p: (p.issued_date, p.project_name or ""),
            reverse=True,
        )
        if not permits:
            detail = "; ".join(errors) if errors else "no development agenda items parsed"
            raise RuntimeError(f"Vineyard planning source returned no usable records: {detail}")

        newest = max(p.issued_date for p in permits)
        note = (
            "Official Utah Public Notice Vineyard Planning Commission agendas; "
            f"{len(permits)} project-specific planning item(s), latest meeting {newest}; "
            "cancellations and policy-only ordinance items excluded; planning-stage intelligence only"
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
            text = re.sub(r"\s+", " ", " ".join(anchor.stripped_strings)).strip().lower()
            if "cancel" in text:
                continue
            url = urljoin(source_url, href)
            if url in seen:
                continue
            seen.add(url)
            found.append(url)
        return found

    @classmethod
    def parse_notice_page(cls, html: str, source_url: str) -> list[Permit]:
        soup = BeautifulSoup(html, "html.parser")
        text = re.sub(r"\s+", " ", soup.get_text(" ", strip=True)).strip()
        lowered = text.lower()
        if "cancellation notice" in lowered or "cancelation notice" in lowered:
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

            project_code = cls._project_code(item)
            stable = project_code or hashlib.sha1(item.lower().encode("utf-8")).hexdigest()[:12].upper()
            digest = hashlib.sha1(
                f"{stable}|{event_date}|{source_url}".lower().encode("utf-8")
            ).hexdigest()[:12].upper()
            permit_number = f"VIN-PLAN-{project_code or digest}"

            permits.append(
                Permit(
                    state="UT",
                    jurisdiction=cls.name,
                    permit_number=permit_number,
                    issued_date=event_date,
                    permit_type=cls._permit_type(item),
                    address=cls._address(item),
                    project_name=item,
                    status="Planning Commission Agenda",
                    source_name="Utah Public Notice - Vineyard Planning Commission",
                    source_url=source_url,
                    raw={
                        "lead_stage": "PLANNING",
                        "hearing_date": event_date,
                        "date_semantics": "scheduled_planning_meeting_date",
                        "project_code": project_code,
                        "agenda_item": item,
                    },
                )
            )
        return permits

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

    @staticmethod
    def _description(text: str) -> str:
        match = re.search(
            r"Description/Agenda\s+(.*?)(?:Notice of Special Accommodations|Meeting Information|Notice Posting Details|Download Attachments|$)",
            text,
            flags=re.I,
        )
        return match.group(1).strip() if match else ""

    @staticmethod
    def _agenda_items(description: str) -> list[str]:
        matches = re.findall(
            r"\b\d+\.\d+\.\s+(.*?)(?=\s+\d+\.\d+\.\s+|\s+\d+\.\s+[A-Z][A-Z ]{2,}|$)",
            description,
            flags=re.I,
        )
        return [re.sub(r"\s+", " ", item).strip(" .") for item in matches if item.strip()]

    @staticmethod
    def _project_code(item: str) -> str | None:
        match = re.search(r"\bPLAN\d{2}-\d{4}\b", item, flags=re.I)
        return match.group(0).upper() if match else None

    @staticmethod
    def _permit_type(item: str) -> str:
        lowered = item.lower()
        if "site plan" in lowered:
            return "Planning Site Plan"
        if "conditional use" in lowered:
            return "Planning Conditional Use"
        if "development agreement" in lowered:
            return "Planning Development Agreement"
        if "final plat" in lowered or "preliminary plat" in lowered or "subdivision" in lowered:
            return "Planning Subdivision/Plat"
        if "rezone" in lowered or "rezoning" in lowered:
            return "Planning Rezone"
        if "annex" in lowered:
            return "Planning Annexation"
        return "Planning Review"

    @staticmethod
    def _address(item: str) -> str:
        match = re.search(
            r"\b\d{2,5}\s+(?:North|South|East|West|N|S|E|W)\s+[A-Za-z0-9 .'-]+",
            item,
            flags=re.I,
        )
        return re.sub(r"\s+", " ", match.group(0)).strip(" .") if match else ""
