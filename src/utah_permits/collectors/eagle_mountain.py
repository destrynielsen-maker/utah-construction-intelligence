from __future__ import annotations

import hashlib
import re
from datetime import date
from urllib.parse import urljoin

import requests
from bs4 import BeautifulSoup

from .base import CollectionResult, new_session
from ..models import Permit


NOTICE_RE = re.compile(
    r"^(?P<month>\d{1,2})[.\-/](?P<day>\d{1,2})[.\-/](?P<year>\d{2,4})\s+"
    r"(?P<label>PCPH|Planning\s+Commission\s+Public\s+Hearing)\s+(?P<title>.+)$",
    flags=re.I,
)

DEVELOPMENT_SIGNALS = (
    "development agreement",
    "master development",
    "rezone",
    "rezoning",
    "subdivision",
    "site plan",
    "plat",
    "annex",
    "conditional use",
    "general plan",
    "future land use",
    "mixed use",
    "mixed-use",
)


class EagleMountainCollector:
    name = "Eagle Mountain"
    SCOPE_ID = "planning-public-notices-v1"
    notices_url = "https://eaglemountain.gov/government/city-recorder/"

    def collect(self, session: requests.Session | None = None) -> CollectionResult:
        session = session or new_session()
        response = session.get(self.notices_url, timeout=45)
        response.raise_for_status()
        permits = self.parse_page(response.text, response.url)
        newest = max((p.raw.get("hearing_date", "") for p in permits), default="unknown")
        return CollectionResult(
            self.name,
            permits,
            self.notices_url,
            (
                "Official Eagle Mountain Recorder current public notices; "
                f"{len(permits)} development hearing item(s), latest hearing {newest}; "
                "planning-stage intelligence only; OpenGov is treated as a submission portal, not a bulk feed"
            ),
            scope_id=self.SCOPE_ID,
        )

    @classmethod
    def parse_page(cls, html: str, source_url: str) -> list[Permit]:
        soup = BeautifulSoup(html, "html.parser")
        permits: list[Permit] = []
        seen: set[str] = set()

        for anchor in soup.find_all("a", href=True):
            text = re.sub(r"\s+", " ", " ".join(anchor.stripped_strings)).strip()
            match = NOTICE_RE.match(text)
            if not match:
                continue

            hearing_date = cls._date_from_match(match)
            title = re.sub(r"\s+", " ", match.group("title")).strip()
            detail_url = urljoin(source_url, anchor["href"])

            for project in cls._project_items(title):
                digest = hashlib.sha1(
                    f"{project}|{hearing_date}|{detail_url}".lower().encode("utf-8")
                ).hexdigest()[:12].upper()
                permit_number = f"EAGLE-PLAN-{digest}"
                if permit_number in seen:
                    continue
                seen.add(permit_number)

                permits.append(
                    Permit(
                        state="UT",
                        jurisdiction=cls.name,
                        permit_number=permit_number,
                        issued_date=hearing_date,
                        permit_type="Planning Public Hearing",
                        address="",
                        project_name=project,
                        status="Planning Commission Public Hearing",
                        source_name="Eagle Mountain Planning Commission Public Notices",
                        source_url=detail_url,
                        raw={
                            "lead_stage": "PLANNING",
                            "hearing_date": hearing_date,
                            "date_semantics": "scheduled_public_hearing_date",
                            "notice_title": title,
                        },
                    )
                )

        return sorted(permits, key=lambda p: (p.issued_date, p.project_name or ""), reverse=True)

    @staticmethod
    def _date_from_match(match: re.Match[str]) -> str:
        year = int(match.group("year"))
        if year < 100:
            year += 2000
        return date(year, int(match.group("month")), int(match.group("day"))).isoformat()

    @staticmethod
    def _project_items(title: str) -> list[str]:
        # Public-hearing notices can bundle development projects with unrelated
        # policy topics. Split the title and retain only clear development signals.
        normalized = re.sub(r"\s+and\s+", ", ", title, flags=re.I)
        items: list[str] = []
        for piece in normalized.split(","):
            project = piece.strip(" \t-–—")
            if not project:
                continue
            lowered = project.lower()
            if any(signal in lowered for signal in DEVELOPMENT_SIGNALS):
                items.append(project)
        return items
