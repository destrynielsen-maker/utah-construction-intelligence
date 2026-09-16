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
    "subdivision",
    "planned unit development",
    "pud",
    "development agreement",
    "project master plan",
    "site plan",
    "rezone",
    "zone change",
    "townhome",
    "multifamily",
    "multiple family",
    "residential lots",
    "commercial",
)

POLICY_ONLY_SIGNALS = (
    "title 10",
    "title 11",
    "zone text amendment",
    "affordable and moderate income housing",
    "fire sprinkler",
    "home occupation",
    "planning commission based on state law",
)

LOW_VALUE_SIGNALS = (
    "special exception for increased lot coverage",
    "additional building height",
)


class FarmingtonCollector:
    name = "Farmington"
    SCOPE_ID = "city-public-notices+pmn-planning-v1"
    public_notices_url = "https://farmington.utah.gov/public-notices/"
    public_body_url = "https://www.utah.gov/pmn/sitemap/publicbody/1588.html"
    notices_url = public_notices_url
    MAX_NOTICE_PAGES = 8

    def collect(self, session: requests.Session | None = None) -> CollectionResult:
        session = session or new_session()
        permits: list[Permit] = []
        errors: list[str] = []

        try:
            current = session.get(self.public_notices_url, timeout=45)
            current.raise_for_status()
            permits.extend(self.parse_city_public_notices(current.text, current.url))
        except Exception as exc:
            errors.append(f"city notices: {type(exc).__name__}: {exc}")

        try:
            body = session.get(self.public_body_url, timeout=45)
            body.raise_for_status()
            notice_urls = self.discover_notice_urls(body.text, body.url)
            for notice_url in notice_urls[: self.MAX_NOTICE_PAGES]:
                try:
                    notice = session.get(notice_url, timeout=45)
                    notice.raise_for_status()
                    permits.extend(self.parse_pmn_notice(notice.text, notice.url))
                except Exception as exc:
                    errors.append(f"pmn notice: {type(exc).__name__}: {exc}")
        except Exception as exc:
            errors.append(f"pmn body: {type(exc).__name__}: {exc}")

        by_key: dict[str, Permit] = {}
        for permit in permits:
            old = by_key.get(permit.permit_number)
            if old is None or permit.issued_date > old.issued_date:
                by_key[permit.permit_number] = permit

        permits = sorted(
            by_key.values(),
            key=lambda p: (p.issued_date, p.project_name or ""),
            reverse=True,
        )
        if not permits:
            detail = "; ".join(errors) if errors else "no project-specific planning items parsed"
            raise RuntimeError(f"Farmington planning sources returned no usable records: {detail}")

        newest = max(p.issued_date for p in permits)
        city_count = sum(p.raw.get("source_kind") == "city_public_notice" for p in permits)
        pmn_count = sum(p.raw.get("source_kind") == "pmn_planning_notice" for p in permits)
        note = (
            "Official Farmington City Public Notices plus Utah Public Notice Planning Commission records; "
            f"{len(permits)} project-specific planning/development item(s) ({city_count} city-current, {pmn_count} PMN backfill), "
            f"latest activity {newest}; addresses, lot counts and acreage retained when available; "
            "citywide code-policy, home occupation and low-value special-exception items excluded; "
            "planning/development-stage intelligence only"
        )
        if errors:
            note += f"; {len(errors)} source/page error(s) encountered"

        return CollectionResult(
            self.name,
            permits,
            self.public_notices_url,
            note,
            scope_id=self.SCOPE_ID,
        )

    @classmethod
    def parse_city_public_notices(cls, html: str, source_url: str) -> list[Permit]:
        soup = BeautifulSoup(html, "html.parser")
        permits: list[Permit] = []
        for row in soup.find_all("tr"):
            cells = row.find_all(["td", "th"])
            if len(cells) < 2:
                continue
            date_value = cls._parse_date(cls._clean(cells[0].get_text(" ", strip=True)))
            text = cls._clean(cells[1].get_text(" ", strip=True))
            if not date_value or "planning commission" not in text.lower():
                continue

            parts = re.split(r"\s+[–—-]\s+", text)
            for part in parts:
                item = cls._clean(part)
                if cls._keep_item(item):
                    permit = cls._permit_from_item(
                        item,
                        date_value,
                        source_url,
                        "city_public_notice",
                    )
                    if permit:
                        permits.append(permit)
        return permits

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
            if "notice" not in text and "agenda" not in text and "hearing" not in text:
                continue
            url = urljoin(source_url, href)
            if url not in seen:
                seen.add(url)
                found.append(url)
        return found

    @classmethod
    def parse_pmn_notice(cls, html: str, source_url: str) -> list[Permit]:
        soup = BeautifulSoup(html, "html.parser")
        text = cls._clean(soup.get_text(" ", strip=True))
        lowered = text.lower()
        if "notice of cancellation" in lowered or "meeting cancelled" in lowered or "meeting canceled" in lowered:
            return []

        event_date = cls._event_date(text)
        description = cls._description(text)
        if not event_date or not description:
            return []

        items: list[str] = []
        if "consider the following:" in description.lower():
            body = re.split(r"consider the following:\s*", description, maxsplit=1, flags=re.I)[1]
            items.extend(re.split(r"\s+[–—-]\s+", " " + body))

        numbered = re.findall(
            r"(?:^|\s)\d+\.\s+(.*?)(?=(?:\s+\d+\.\s)|(?:\s+[A-Z][A-Z /&-]+APPLICATIONS?\s+-)|$)",
            description,
            flags=re.I,
        )
        items.extend(numbered)

        permits: list[Permit] = []
        seen: set[str] = set()
        for raw_item in items:
            item = cls._clean(raw_item)
            if not cls._keep_item(item):
                continue
            permit = cls._permit_from_item(item, event_date, source_url, "pmn_planning_notice")
            if permit and permit.permit_number not in seen:
                seen.add(permit.permit_number)
                permits.append(permit)
        return permits

    @classmethod
    def _keep_item(cls, item: str) -> bool:
        lowered = item.lower()
        if any(signal in lowered for signal in POLICY_ONLY_SIGNALS):
            return False
        if any(signal in lowered for signal in LOW_VALUE_SIGNALS):
            return False
        return any(signal in lowered for signal in DEVELOPMENT_SIGNALS)

    @classmethod
    def _permit_from_item(
        cls,
        item: str,
        activity_date: str,
        source_url: str,
        source_kind: str,
    ) -> Permit | None:
        address = cls._address(item)
        project_name = cls._project_name(item, address)
        if not project_name:
            return None
        stable = (address or project_name).lower()
        digest = hashlib.sha1(stable.encode("utf-8")).hexdigest()[:12].upper()
        return Permit(
            state="UT",
            jurisdiction=cls.name,
            permit_number=f"FAR-PLAN-{digest}",
            issued_date=activity_date,
            permit_type=cls._permit_type(item),
            address=address,
            project_name=project_name,
            units=cls._units(item),
            status="Planning/Development Activity",
            source_name="Farmington City / Utah Public Notice Planning Commission",
            source_url=source_url,
            raw={
                "lead_stage": "PLANNING",
                "source_kind": source_kind,
                "activity_date": activity_date,
                "date_semantics": "planning_notice_or_hearing_date",
                "acreage": cls._acreage(item),
                "planning_item": item,
            },
        )

    @staticmethod
    def _clean(value: str) -> str:
        return re.sub(r"\s+", " ", value or "").strip(" .–—-")

    @staticmethod
    def _parse_date(value: str) -> str | None:
        for fmt in ("%B %d, %Y", "%b %d, %Y"):
            try:
                return datetime.strptime(value, fmt).date().isoformat()
            except ValueError:
                pass
        return None

    @classmethod
    def _event_date(cls, text: str) -> str | None:
        match = re.search(
            r"Event Start Date & Time\s+([A-Za-z]+\s+\d{1,2},\s+\d{4})",
            text,
            flags=re.I,
        )
        return cls._parse_date(match.group(1)) if match else None

    @classmethod
    def _description(cls, text: str) -> str:
        match = re.search(
            r"Description/Agenda\s+(.*?)(?:Notice of Special Accommodations|Meeting Information|Notice Posting Details|Download Attachments|$)",
            text,
            flags=re.I,
        )
        return cls._clean(match.group(1)) if match else ""

    @classmethod
    def _address(cls, item: str) -> str:
        patterns = (
            r"\bat\s+(approximately\s+)?(\d{1,5}[^.;]+?)(?=\s+for\b|\s+from\b|\.|;|$)",
            r"\bproperty\s+at\s+(approximately\s+)?(\d{1,5}[^.;]+?)(?=\s+for\b|\s+from\b|\.|;|$)",
        )
        for pattern in patterns:
            match = re.search(pattern, item, flags=re.I)
            if match:
                return cls._clean(match.group(2))
        return ""

    @classmethod
    def _project_name(cls, item: str, address: str) -> str:
        named_patterns = (
            r"for the\s+(.+?)\s+project\b",
            r"for\s+the\s+(.+?\s+Subdivision)\b",
            r"(?:Master Plan for|Agreement for)\s+the\s+(.+?\s+Subdivision)\b",
            r"\b([A-Z][A-Za-z0-9 '&.-]+\s+Subdivision)\b",
        )
        for pattern in named_patterns:
            match = re.search(pattern, item, flags=re.I)
            if match:
                return cls._clean(match.group(1))
        if address:
            if "rezone" in item.lower():
                return f"Rezone - {address}"
            if "site plan" in item.lower():
                return f"Site Plan - {address}"
        return cls._clean(item)[:180]

    @staticmethod
    def _permit_type(item: str) -> str:
        lowered = item.lower()
        if "subdivision" in lowered and ("development agreement" in lowered or "pud" in lowered):
            return "Planning Subdivision/PUD"
        if "subdivision" in lowered:
            return "Planning Subdivision/Plat"
        if "site plan" in lowered:
            return "Planning Site Plan"
        if "rezone" in lowered or "zone change" in lowered:
            return "Planning Rezone"
        if "development agreement" in lowered or "project master plan" in lowered:
            return "Planning Development Agreement"
        return "Planning Review"

    @staticmethod
    def _units(item: str) -> int | None:
        for pattern in (
            r"\b(\d{1,4})\s+single family residential lots\b",
            r"\b(\d{1,4})\s+townhomes\b",
            r"\b(\d{1,4})\s+(?:residential\s+)?lots\b",
            r"\b(\d{1,4})[- ]lot\b",
        ):
            match = re.search(pattern, item, flags=re.I)
            if match:
                return int(match.group(1))
        return None

    @staticmethod
    def _acreage(item: str) -> float | None:
        match = re.search(r"\b(?:approximately\s+)?([0-9.]+)\s+acres?\b", item, flags=re.I)
        if not match:
            return None
        try:
            return float(match.group(1))
        except ValueError:
            return None
