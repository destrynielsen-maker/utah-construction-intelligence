from __future__ import annotations

import hashlib
import re
from datetime import datetime
from urllib.parse import urljoin

import requests
from bs4 import BeautifulSoup

from .base import CollectionResult, new_session
from ..models import Permit


POLICY_ONLY_SIGNALS = (
    "text amendment",
    "land use authorities",
    "appeal authorities",
    "city code",
    "ordinance amendment",
)


class WestJordanCollector:
    name = "West Jordan"
    SCOPE_ID = "pmn-planning-public-hearings-v1"
    public_body_url = "https://www.utah.gov/pmn/sitemap/publicbody/396.html"
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
            detail = "; ".join(errors) if errors else "no project-specific hearing items parsed"
            raise RuntimeError(f"West Jordan planning source returned no usable records: {detail}")

        newest = max(p.issued_date for p in permits)
        note = (
            "Official Utah Public Notice West Jordan Planning Commission public-hearing notices; "
            f"{len(permits)} project-specific planning/development item(s), latest hearing {newest}; "
            "addresses, lot counts and acreage retained when available; citywide text/code amendments excluded; "
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
            if text not in {"public hearing", "public notice"} and "notice of public hearing" not in text:
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
        for item in cls._hearing_items(description):
            normalized = item.lower()
            if any(signal in normalized for signal in POLICY_ONLY_SIGNALS):
                continue

            project_name = cls._project_name(item)
            address = cls._address(item)
            if not project_name or not address:
                continue

            stable = f"{project_name}|{address}".lower()
            digest = hashlib.sha1(stable.encode("utf-8")).hexdigest()[:12].upper()
            permits.append(
                Permit(
                    state="UT",
                    jurisdiction=cls.name,
                    permit_number=f"WJ-PLAN-{digest}",
                    issued_date=event_date,
                    permit_type=cls._permit_type(item),
                    address=address,
                    project_name=project_name,
                    units=cls._units(item),
                    status="Planning Commission Public Hearing",
                    source_name="Utah Public Notice - West Jordan Planning Commission",
                    source_url=source_url,
                    raw={
                        "lead_stage": "PLANNING",
                        "hearing_date": event_date,
                        "date_semantics": "scheduled_public_hearing_date",
                        "acreage": cls._acreage(item),
                        "applicant": cls._applicant(item),
                        "hearing_item": item,
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
    def _hearing_items(cls, description: str) -> list[str]:
        match = re.search(
            r"regarding the following:\s*(.*?)(?:\s+If you are interested in participating|\s+Alternatively, you may share|\s+In accordance with the Americans with Disabilities Act|$)",
            description,
            flags=re.I,
        )
        if not match:
            return []
        body = match.group(1)
        parts = re.split(r"\s+-\s+", " " + body)
        return [cls._clean(part) for part in parts if cls._clean(part)]

    @classmethod
    def _project_name(cls, item: str) -> str:
        return cls._clean(item.split(";", 1)[0])

    @classmethod
    def _address(cls, item: str) -> str:
        fields = [cls._clean(field) for field in item.split(";")]
        if len(fields) < 2:
            return ""
        candidate = fields[1]
        if re.search(r"\d", candidate):
            return candidate
        return ""

    @staticmethod
    def _permit_type(item: str) -> str:
        lowered = item.lower()
        if "subdivision" in lowered and "site plan" in lowered:
            return "Planning Site Plan/Subdivision"
        if "subdivision" in lowered:
            return "Planning Subdivision/Plat"
        if "preliminary site plan" in lowered or "site plan" in lowered:
            return "Planning Site Plan"
        if "rezone" in lowered or "future land use map amendment" in lowered:
            return "Planning Rezone/Plan Amendment"
        if "conditional use permit" in lowered:
            return "Planning Conditional Use"
        return "Planning Review"

    @staticmethod
    def _units(item: str) -> int | None:
        for pattern in (
            r"\b(\d{1,4})\s+lots\b",
            r"\b(\d{1,4})-lot\b",
        ):
            match = re.search(pattern, item, flags=re.I)
            if match:
                return int(match.group(1))
        return None

    @staticmethod
    def _acreage(item: str) -> float | None:
        for pattern in (
            r"\b([0-9.]+)\s+acres\b",
            r"\bon\s+([0-9.]+)\s+acres\b",
        ):
            match = re.search(pattern, item, flags=re.I)
            if match:
                try:
                    return float(match.group(1))
                except ValueError:
                    return None
        return None

    @classmethod
    def _applicant(cls, item: str) -> str:
        match = re.search(r";\s*([^;]+?)\s*\((?:applicant|Applicant)\)\s*$", item)
        return cls._clean(match.group(1)) if match else ""
