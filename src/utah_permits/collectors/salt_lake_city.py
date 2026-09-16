from __future__ import annotations

import re
from datetime import datetime
from urllib.parse import urljoin

import requests
from bs4 import BeautifulSoup

from .base import CollectionResult, new_session
from ..models import Permit


EXCLUDED_SIGNALS = (
    "text amendment",
    "community plan update",
    "street vacation",
    "alley vacation",
    "alley closure",
    "designation of",
    "landmark site",
    "daily water use limits",
    "definition of family",
    "expiration of land use approvals",
)


class SaltLakeCityCollector:
    name = "Salt Lake City"
    SCOPE_ID = "planning-active-open-houses-v1"
    landing_url = "https://www.slc.gov/planning/public-meetings/open-houses/"
    notices_url = landing_url

    def collect(self, session: requests.Session | None = None) -> CollectionResult:
        session = session or new_session()
        response = session.get(self.landing_url, timeout=45)
        response.raise_for_status()
        permits = self.parse_page(response.text, response.url)
        if not permits:
            raise RuntimeError("Salt Lake City active planning source returned no usable project records")

        by_primary: dict[str, Permit] = {}
        for permit in permits:
            old = by_primary.get(permit.permit_number)
            if old is None or permit.issued_date > old.issued_date:
                by_primary[permit.permit_number] = permit
        permits = sorted(
            by_primary.values(),
            key=lambda p: (p.issued_date, p.project_name or ""),
            reverse=True,
        )
        newest = max(p.issued_date for p in permits)
        note = (
            "Official Salt Lake City Planning Active Online Open Houses; "
            f"{len(permits)} location-specific planning/development project(s), latest posting {newest}; "
            "project locations, application types and petition numbers retained; citywide policy, community-plan, "
            "street/alley-vacation and landmark-only items excluded; planning/development-stage intelligence only. "
            "The post-migration Accela Citizen Access building portal is current and publicly searchable for individual "
            "records but is not treated here as a stable bulk permit feed."
        )
        return CollectionResult(
            self.name,
            permits,
            self.landing_url,
            note,
            scope_id=self.SCOPE_ID,
        )

    @classmethod
    def parse_page(cls, html: str, source_url: str) -> list[Permit]:
        soup = BeautifulSoup(html, "html.parser")
        permits: list[Permit] = []
        for anchor in soup.find_all("a", href=True):
            text = cls._clean(" ".join(anchor.stripped_strings))
            if "Posted on:" not in text or "Application Type:" not in text:
                continue
            if "Petition Number" not in text:
                continue

            posted_date = cls._posted_date(text)
            location = cls._field(text, "Project Location:", "Application Type:")
            application_type = cls._field(
                text,
                "Application Type:",
                ("Petition Number(s):", "Petition Number:"),
            )
            petitions = cls._petition_numbers(text)
            title = cls._clean(text.split("Posted on:", 1)[0])
            if not posted_date or not location or not petitions or not title:
                continue

            normalized = f"{title} {location} {application_type}".lower()
            if location.strip().lower() == "citywide":
                continue
            if any(signal in normalized for signal in EXCLUDED_SIGNALS):
                continue

            permit = Permit(
                state="UT",
                jurisdiction=cls.name,
                permit_number=f"SLC-PLAN-{petitions[0]}",
                issued_date=posted_date,
                permit_type=cls._permit_type(application_type, title),
                address=location,
                project_name=title,
                units=cls._units(text),
                status="Active Planning Online Open House",
                source_name="Salt Lake City Planning - Active Online Open Houses",
                source_url=urljoin(source_url, anchor.get("href", "")),
                raw={
                    "lead_stage": "PLANNING",
                    "posted_date": posted_date,
                    "date_semantics": "active_planning_open_house_posted_date",
                    "petition_numbers": petitions,
                    "application_type": application_type,
                    "project_location": location,
                },
            )
            permits.append(permit)
        return permits

    @staticmethod
    def _clean(value: str) -> str:
        return re.sub(r"\s+", " ", value or "").strip(" .")

    @staticmethod
    def _posted_date(text: str) -> str | None:
        match = re.search(
            r"Posted on:\s*([A-Za-z]+\s+\d{1,2})(?:st|nd|rd|th)?,\s*(\d{4})",
            text,
            flags=re.I,
        )
        if not match:
            return None
        raw = f"{match.group(1)}, {match.group(2)}"
        try:
            return datetime.strptime(raw, "%B %d, %Y").date().isoformat()
        except ValueError:
            return None

    @classmethod
    def _field(
        cls,
        text: str,
        start: str,
        end: str | tuple[str, ...],
    ) -> str:
        starts = re.search(re.escape(start), text, flags=re.I)
        if not starts:
            return ""
        remainder = text[starts.end():]
        endings = (end,) if isinstance(end, str) else end
        positions: list[int] = []
        for marker in endings:
            found = re.search(re.escape(marker), remainder, flags=re.I)
            if found:
                positions.append(found.start())
        value = remainder[: min(positions)] if positions else remainder
        return cls._clean(value)

    @staticmethod
    def _petition_numbers(text: str) -> list[str]:
        values = re.findall(r"\bPLN[A-Z]{2,8}\d{4}-\d{4,5}\b", text, flags=re.I)
        result: list[str] = []
        for value in values:
            normalized = value.upper()
            if normalized not in result:
                result.append(normalized)
        return result

    @staticmethod
    def _permit_type(application_type: str, title: str) -> str:
        lowered = f"{application_type} {title}".lower()
        if "new construction" in lowered:
            return "Planning New Construction Review"
        if "preliminary subdivision" in lowered or "subdivision" in lowered:
            return "Planning Subdivision/Plat"
        if "planned development" in lowered:
            return "Planning Planned Development"
        if "design review" in lowered:
            return "Planning Design Review"
        if "conditional use" in lowered:
            return "Planning Conditional Use"
        if "zoning map" in lowered or "rezone" in lowered:
            return "Planning Rezone"
        if "general plan" in lowered:
            return "Planning General Plan Amendment"
        if "major alteration" in lowered:
            return "Planning Major Alteration"
        return "Planning Review"

    @staticmethod
    def _units(text: str) -> int | None:
        for pattern in (
            r"\b(\d{1,4})[- ]unit\b",
            r"\b(\d{1,4})\s+(?:residential\s+)?units\b",
            r"\b(\d{1,4})[- ]lot\b",
        ):
            match = re.search(pattern, text, flags=re.I)
            if match:
                return int(match.group(1))
        return None
