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
    "commercial",
    "condominium",
    "development agreement",
    "final plat",
    "mixed use",
    "mixed-use",
    "multifamily",
    "preliminary subdivision plat",
    "rezone",
    "site plan",
    "subdivision",
    "townhome",
    "vicinity plan",
    "zone change",
)

POLICY_ONLY_SIGNALS = (
    "code text amendment",
    "city wide",
    "city-wide",
)


class PleasantGroveCollector:
    name = "Pleasant Grove"
    SCOPE_ID = "pmn-planning-hearings-v1"
    public_body_url = "https://www.utah.gov/pmn/sitemap/publicbody/1404.html"
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

        by_key = {permit.key: permit for permit in permits}
        permits = sorted(
            by_key.values(),
            key=lambda p: (p.issued_date, p.project_name or ""),
            reverse=True,
        )
        if not permits:
            detail = "; ".join(errors) if errors else "no development hearing items parsed"
            raise RuntimeError(f"Pleasant Grove planning source returned no usable records: {detail}")

        newest = max(p.issued_date for p in permits)
        note = (
            "Official Utah Public Notice Pleasant Grove Planning Commission hearing notices; "
            f"{len(permits)} project-specific planning item(s), latest hearing {newest}; "
            "citywide code-text amendments excluded; planning-stage intelligence only"
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
            text = re.sub(r"\s+", " ", " ".join(anchor.stripped_strings)).strip().lower()
            href = anchor.get("href", "")
            if "planning commission public hearing notice" not in text:
                continue
            if "/pmn/sitemap/notice/" not in href:
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
        event_date = cls._event_date(text)
        description = cls._description(text)
        if not event_date or not description:
            return []

        permits: list[Permit] = []
        for title in cls._hearing_items(description):
            normalized = title.lower()
            if any(signal in normalized for signal in POLICY_ONLY_SIGNALS):
                continue
            if not any(signal in normalized for signal in DEVELOPMENT_SIGNALS):
                continue

            digest = hashlib.sha1(
                f"{title}|{event_date}|{source_url}".lower().encode("utf-8")
            ).hexdigest()[:12].upper()
            permits.append(
                Permit(
                    state="UT",
                    jurisdiction=cls.name,
                    permit_number=f"PG-PLAN-{digest}",
                    issued_date=event_date,
                    permit_type="Planning Public Hearing",
                    address=cls._address_from_title(title),
                    project_name=title,
                    status="Planning Commission Public Hearing",
                    source_name="Utah Public Notice - Pleasant Grove Planning Commission",
                    source_url=source_url,
                    raw={
                        "lead_stage": "PLANNING",
                        "hearing_date": event_date,
                        "date_semantics": "scheduled_public_hearing_date",
                        "notice_text": title,
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
    def _hearing_items(description: str) -> list[str]:
        matches = re.findall(
            r"Public Hearing:\s*(.*?)(?=(?:Public Hearing:|For assistance|Posted by:|\*Note:|$))",
            description,
            flags=re.I,
        )
        return [re.sub(r"\s+", " ", value).strip(" .") for value in matches if value.strip()]

    @staticmethod
    def _address_from_title(title: str) -> str:
        match = re.search(
            r"Located at(?: approx\.| approximately)?\s+(.+?)(?:\s*\([^)]*\)|\s+Public Hearing to consider|$)",
            title,
            flags=re.I,
        )
        return re.sub(r"\s+", " ", match.group(1)).strip(" .") if match else ""
