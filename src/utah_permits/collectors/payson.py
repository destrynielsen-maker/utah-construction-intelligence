from __future__ import annotations

import hashlib
import re
from datetime import date
from urllib.parse import urljoin

import requests
from bs4 import BeautifulSoup

from .base import CollectionResult, new_session
from ..models import Permit


DEVELOPMENT_SIGNALS = (
    "annex",
    "commercial",
    "conditional use",
    "development agreement",
    "final plat",
    "general plan amendment",
    "mixed use",
    "mixed-use",
    "multifamily",
    "preliminary plat",
    "rezone",
    "rezoning",
    "site plan",
    "subdivision",
    "townhome",
    "zone change",
)

GENERIC_TITLES = {
    "payson city planning commission meeting",
    "payson city planning commission public hearing",
    "planning commission meeting",
    "planning commission public hearing",
    "general plan amendment",
    "zone change",
}


class PaysonCollector:
    name = "Payson"
    SCOPE_ID = "pmn-planning-hearings-v1"
    public_body_url = "https://www.utah.gov/pmn/sitemap/publicbody/668.html"
    notices_url = public_body_url

    def collect(self, session: requests.Session | None = None) -> CollectionResult:
        session = session or new_session()
        response = session.get(self.public_body_url, timeout=45)
        response.raise_for_status()
        permits = self.parse_public_body(response.text, response.url)
        if not permits:
            raise RuntimeError("Payson Planning Commission source returned no project-specific hearing items")

        newest = max(p.issued_date for p in permits)
        note = (
            "Official Utah Public Notice Payson Planning Commission notices; "
            f"{len(permits)} project-specific hearing item(s), latest hearing {newest}; "
            "cancelled meetings and generic agenda notices excluded; planning-stage intelligence only; "
            "the City-linked Applications Currently Under Review StoryMap is retained only as historical context because its ArcGIS item was last modified in 2024"
        )
        return CollectionResult(
            self.name,
            permits,
            self.public_body_url,
            note,
            scope_id=self.SCOPE_ID,
        )

    @classmethod
    def parse_public_body(cls, html: str, source_url: str) -> list[Permit]:
        soup = BeautifulSoup(html, "html.parser")
        permits: list[Permit] = []

        for row in soup.find_all("tr"):
            row_text = re.sub(r"\s+", " ", " ".join(row.stripped_strings)).strip()
            if not row_text or "cancel" in row_text.lower():
                continue
            event_date = cls._event_date(row_text)
            if not event_date:
                continue

            notice_anchor = None
            for anchor in row.find_all("a", href=True):
                if "/pmn/sitemap/notice/" in anchor.get("href", ""):
                    notice_anchor = anchor
                    break
            if notice_anchor is None:
                continue

            notice_title = cls._clean_text(" ".join(notice_anchor.stripped_strings))
            notice_url = urljoin(source_url, notice_anchor.get("href", ""))
            candidates: list[tuple[str, str]] = [(notice_title, "notice_title")]

            for anchor in row.find_all("a", href=True):
                attachment = cls._clean_text(" ".join(anchor.stripped_strings))
                if not attachment.lower().endswith(".pdf"):
                    continue
                cleaned = cls._clean_attachment_title(attachment)
                if cleaned:
                    candidates.append((cleaned, "attachment_title"))

            for candidate, origin in candidates:
                if not cls._is_project_specific(candidate):
                    continue
                permit = cls._permit_from_candidate(
                    candidate=candidate,
                    event_date=event_date,
                    notice_title=notice_title,
                    notice_url=notice_url,
                    origin=origin,
                )
                permits.append(permit)

        by_key: dict[str, Permit] = {}
        for permit in permits:
            existing = by_key.get(permit.key)
            if existing is None or permit.issued_date > existing.issued_date:
                by_key[permit.key] = permit
        return sorted(
            by_key.values(),
            key=lambda p: (p.issued_date, p.project_name or ""),
            reverse=True,
        )

    @classmethod
    def _permit_from_candidate(
        cls,
        candidate: str,
        event_date: str,
        notice_title: str,
        notice_url: str,
        origin: str,
    ) -> Permit:
        stable_title = cls._stable_title(candidate)
        digest = hashlib.sha1(stable_title.lower().encode("utf-8")).hexdigest()[:12].upper()
        return Permit(
            state="UT",
            jurisdiction=cls.name,
            permit_number=f"PAY-PLAN-{digest}",
            issued_date=event_date,
            permit_type=cls._permit_type(candidate),
            address=cls._address(candidate),
            project_name=candidate,
            status="Planning Commission Public Hearing",
            source_name="Utah Public Notice - Payson Planning Commission",
            source_url=notice_url,
            raw={
                "lead_stage": "PLANNING",
                "hearing_date": event_date,
                "date_semantics": "scheduled_public_hearing_date",
                "notice_title": notice_title,
                "candidate_origin": origin,
            },
        )

    @staticmethod
    def _clean_text(value: str) -> str:
        return re.sub(r"\s+", " ", value or "").strip(" .")

    @classmethod
    def _clean_attachment_title(cls, value: str) -> str:
        text = cls._clean_text(value)
        text = re.sub(r"\.pdf$", "", text, flags=re.I)
        text = re.sub(r"^PC\s+PH\s+", "", text, flags=re.I)
        text = re.sub(r"^\d{1,2}-\d{1,2}-\d{4}\s+", "", text)
        text = re.sub(r"^\d{1,2}-\d{1,2}-\d{2}\s+", "", text)
        text = re.sub(r"^\d{1,2}-\d{1,2}-\d{4}\s+PC\s+", "", text, flags=re.I)
        text = re.sub(r"^\d{1,2}-\d{1,2}-\d{2}\s+PC\s+", "", text, flags=re.I)
        text = re.sub(r"^PC\s+", "", text, flags=re.I)
        return cls._clean_text(text)

    @staticmethod
    def _event_date(row_text: str) -> str | None:
        match = re.search(r"\b(20\d{2})/(\d{1,2})/(\d{1,2})\b", row_text)
        if not match:
            return None
        try:
            return date(int(match.group(1)), int(match.group(2)), int(match.group(3))).isoformat()
        except ValueError:
            return None

    @classmethod
    def _is_project_specific(cls, candidate: str) -> bool:
        normalized = cls._stable_title(candidate).lower()
        if not any(signal in normalized for signal in DEVELOPMENT_SIGNALS):
            return False
        if normalized in GENERIC_TITLES:
            return False
        if normalized.startswith("payson city planning commission"):
            suffix = re.sub(
                r"^payson city planning commission (?:public hearing|meeting)\s*-?\s*",
                "",
                normalized,
            ).strip()
            if not suffix or suffix in GENERIC_TITLES:
                return False
        return True

    @classmethod
    def _stable_title(cls, candidate: str) -> str:
        text = cls._clean_text(candidate)
        text = re.sub(
            r"^Payson City Planning Commission (?:Public Hearing|Meeting)\s*-?\s*",
            "",
            text,
            flags=re.I,
        )
        return cls._clean_text(text)

    @staticmethod
    def _permit_type(candidate: str) -> str:
        lowered = candidate.lower()
        if "site plan" in lowered:
            return "Planning Site Plan"
        if "subdivision" in lowered or "final plat" in lowered or "preliminary plat" in lowered:
            return "Planning Subdivision/Plat"
        if "zone change" in lowered or "rezone" in lowered or "rezoning" in lowered:
            return "Planning Rezone"
        if "annex" in lowered:
            return "Planning Annexation"
        if "general plan amendment" in lowered:
            return "Planning General Plan Amendment"
        if "development agreement" in lowered:
            return "Planning Development Agreement"
        if "conditional use" in lowered:
            return "Planning Conditional Use"
        return "Planning Review"

    @staticmethod
    def _address(candidate: str) -> str:
        match = re.search(
            r"\b\d{2,5}\s+(?:North|South|East|West|N|S|E|W)\s+[A-Za-z0-9 .'-]+",
            candidate,
            flags=re.I,
        )
        return re.sub(r"\s+", " ", match.group(0)).strip(" .") if match else ""
