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
    "building expansion",
    "commercial",
    "concept plan",
    "conditional use permit",
    "construction",
    "final plat",
    "industrial park",
    "minor subdivision",
    "office building",
    "plat amendment",
    "preliminary plat",
    "site plan",
    "subdivision",
    "warehouse",
)

POLICY_ONLY_SIGNALS = (
    "accessory dwelling",
    "adu",
    "city ordinance",
    "code amendment",
    "development manual amendment",
    "general plan amendment",
    "master plan map amendment",
    "ordinance amendment",
    "street master plan",
    "watershare ordinance",
)


class LindonCollector:
    name = "Lindon"
    SCOPE_ID = "pmn-planning-development-v1"
    public_body_url = "https://www.utah.gov/pmn/sitemap/publicbody/522.html"
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
            detail = "; ".join(errors) if errors else "no project-specific Planning Commission items parsed"
            raise RuntimeError(f"Lindon planning source returned no usable records: {detail}")

        newest = max(p.issued_date for p in permits)
        note = (
            "Official Utah Public Notice Lindon Planning Commission agendas; "
            f"{len(permits)} project-specific development item(s), latest meeting {newest}; "
            "ADU/code/master-plan policy items excluded; planning/development-stage intelligence only"
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
            if "planning commission" not in text:
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
        if "cancelled" in lowered or "canceled" in lowered:
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

            title = cls._stable_title(item)
            digest = hashlib.sha1(title.lower().encode("utf-8")).hexdigest()[:12].upper()
            permits.append(
                Permit(
                    state="UT",
                    jurisdiction=cls.name,
                    permit_number=f"LIN-PLAN-{digest}",
                    issued_date=event_date,
                    permit_type=cls._permit_type(item),
                    address=cls._address(item),
                    project_name=title,
                    area=cls._area(item),
                    status="Planning Commission Agenda",
                    source_name="Utah Public Notice - Lindon Planning Commission",
                    source_url=source_url,
                    raw={
                        "lead_stage": "PLANNING",
                        "meeting_date": event_date,
                        "date_semantics": "scheduled_planning_meeting_date",
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
        body = re.sub(r"^.*?3\.\s+Public Comment\s+", "", description, flags=re.I)
        body = re.split(
            r"\s+(?:Community Development Director Report|Adjourn|Planning Director Report)\b",
            body,
            maxsplit=1,
            flags=re.I,
        )[0]
        matches = re.findall(
            r"(?:^|\s)\d{1,2}\.\s+(.*?)(?=\s+\d{1,2}\.\s+|$)",
            body,
            flags=re.I,
        )
        return [cls._clean(item) for item in matches if cls._clean(item)]

    @classmethod
    def _stable_title(cls, item: str) -> str:
        lowered = item.lower()
        known = (
            ("cottonwood healthcare", "Cottonwood Healthcare Corporate Headquarters"),
            ("jz styles", "JZ Styles Commercial Building"),
            ("lindon harbor industrial park", "Lindon Harbor Industrial Park"),
            ("blackhurst manor", "Blackhurst Manor Subdivision"),
            ("7 brew", "7 Brew Site Plan"),
            ("fortem", "Fortem Building Expansion"),
            ("lindon collision", "Lindon Collision Conditional Use Permit"),
        )
        for signal, title in known:
            if signal in lowered:
                return title

        text = cls._clean(item)
        text = re.sub(
            r"^(?:Site Plan Approval|Site Plan|Minor Subdivision|Conditional Use Permit|Concept Plan Review|Plat Amendment)\s*[-:]\s*",
            "",
            text,
            flags=re.I,
        )
        return cls._clean(text)

    @staticmethod
    def _permit_type(item: str) -> str:
        lowered = item.lower()
        if "conditional use permit" in lowered:
            return "Planning Conditional Use"
        if "site plan" in lowered:
            return "Planning Site Plan"
        if "plat amendment" in lowered:
            return "Planning Plat Amendment"
        if "minor subdivision" in lowered or "subdivision" in lowered:
            return "Planning Subdivision/Plat"
        if "concept plan" in lowered or "building expansion" in lowered:
            return "Planning Concept/Expansion"
        return "Planning Review"

    @classmethod
    def _address(cls, item: str) -> str:
        match = re.search(
            r"\b\d{2,5}\s+(?:N(?:orth)?|S(?:outh)?|E(?:ast)?|W(?:est)?)\.?\s+[A-Za-z0-9 .'-]+?(?=\.|,|\s+into\b|\s+to\b|$)",
            item,
            flags=re.I,
        )
        return cls._clean(match.group(0)) if match else ""

    @staticmethod
    def _area(item: str) -> str | None:
        match = re.search(r"\b([\d,]+)-square-foot\b", item, flags=re.I)
        if not match:
            return None
        return f"{match.group(1)} sq ft"
