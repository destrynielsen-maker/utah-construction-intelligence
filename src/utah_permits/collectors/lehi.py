from __future__ import annotations

import hashlib
import re
from datetime import date, datetime, timedelta
from urllib.parse import urljoin

import requests
from bs4 import BeautifulSoup

from .base import CollectionResult, new_session
from ..models import Permit


TITLE_DATE_RE = re.compile(
    r"\b(January|February|March|April|May|June|July|August|September|October|November|December)\s+(\d{1,2}),\s+(20\d{2})\b",
    re.I,
)
ADDRESS_RE = re.compile(
    r"(?:located\s+(?:at|approximately at|near)|approximately)\s+(.+?)(?:\.|,\s*(?:requesting|for|within)|$)",
    re.I,
)


class LehiCollector:
    name = "Lehi"
    SCOPE_ID = "planning-public-hearings-v1"
    notices_url = "https://www.lehi-ut.gov/news/public-notices/"
    MAX_NOTICE_AGE_DAYS = 120

    def collect(self, session: requests.Session | None = None) -> CollectionResult:
        session = session or new_session()
        notices = self.discover_recent_planning_notices(session)
        permits: list[Permit] = []
        for hearing_date, url in notices:
            response = session.get(url, timeout=45)
            response.raise_for_status()
            permits.extend(self.parse_notice_html(response.text, hearing_date, url))

        if not notices:
            raise RuntimeError("Could not discover recent Lehi Planning Commission notices")

        latest = max((d for d, _ in notices), default="unknown")
        return CollectionResult(
            self.name,
            permits,
            notices[0][1],
            f"Official Lehi Planning Commission public-hearing notices; {len(notices)} notice(s), "
            f"{len(permits)} development item(s), latest hearing {latest}; building portal is public lookup-only",
            scope_id=self.SCOPE_ID,
        )

    def discover_recent_planning_notices(
        self,
        session: requests.Session,
        as_of: date | None = None,
    ) -> list[tuple[str, str]]:
        as_of = as_of or date.today()
        response = session.get(self.notices_url, timeout=45)
        response.raise_for_status()
        soup = BeautifulSoup(response.text, "html.parser")
        cutoff = as_of - timedelta(days=self.MAX_NOTICE_AGE_DAYS)
        found: dict[str, tuple[date, str]] = {}

        for anchor in soup.find_all("a", href=True):
            text = " ".join(anchor.stripped_strings).strip()
            lower = text.lower()
            if "planning commission" not in lower:
                continue
            if "hearing" not in lower and "public hearing" not in lower:
                continue
            match = TITLE_DATE_RE.search(text)
            if not match:
                continue
            month = datetime.strptime(match.group(1), "%B").month
            hearing = date(int(match.group(3)), month, int(match.group(2)))
            if hearing < cutoff or hearing > as_of + timedelta(days=31):
                continue
            url = urljoin(response.url, anchor["href"])
            found[url] = (hearing, url)

        rows = sorted(found.values(), key=lambda item: item[0], reverse=True)
        return [(d.isoformat(), url) for d, url in rows[:6]]

    @classmethod
    def parse_notice_html(cls, html: str, hearing_date: str, source_url: str) -> list[Permit]:
        soup = BeautifulSoup(html, "html.parser")
        root = soup.find("main") or soup.find("article") or soup
        texts: list[str] = []
        for node in root.find_all(["p", "li"]):
            text = " ".join(node.stripped_strings).strip()
            if text and text not in texts:
                texts.append(text)

        project_terms = (
            "subdivision",
            "site plan",
            "preliminary plat",
            "final plat",
            "planned development",
            "planned residential development",
            "planned unit development",
            "area plan",
            "zone change",
            "zoning amendment",
            "mixed use",
            "mixed-use",
            "apartment",
            "townhome",
            "town home",
            "townhouse",
            "condominium",
            "commercial",
            "office",
            "warehouse",
            "industrial",
            "hotel",
            "storage building",
            "residential development",
            "concept plan",
            "development agreement",
        )
        noise_terms = (
            "development code amendment",
            "chapter ",
            "fence",
            "antenna",
            "telecommunications",
            "sign permit",
            "fee schedule",
        )

        permits: list[Permit] = []
        seen: set[str] = set()
        for text in texts:
            lower = text.lower()
            if "public hearing" not in lower and "request" not in lower:
                continue
            if not any(term in lower for term in project_terms):
                continue
            if any(term in lower for term in noise_terms):
                continue
            if text in seen:
                continue
            seen.add(text)

            address = ""
            address_match = ADDRESS_RE.search(text)
            if address_match:
                address = address_match.group(1).strip(" .;,:")

            digest = hashlib.sha1(
                f"{hearing_date}|{text}".lower().encode("utf-8")
            ).hexdigest()[:12].upper()
            permits.append(
                Permit(
                    state="UT",
                    jurisdiction="Lehi",
                    permit_number=f"LEHI-PLAN-{digest}",
                    issued_date=hearing_date,
                    permit_type="Planning Review",
                    project_name=text[:500],
                    address=address,
                    status="Planning Commission Review",
                    source_name="Lehi City Planning Commission Public Hearings",
                    source_url=source_url,
                    raw={
                        "hearing_item": text,
                        "hearing_date": hearing_date,
                        "date_semantics": "planning_hearing_date",
                        "lead_stage": "PLANNING",
                    },
                )
            )
        return permits
