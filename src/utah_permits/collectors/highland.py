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
    "assisted living",
    "commercial",
    "development agreement",
    "final plat",
    "medical",
    "office",
    "preliminary plat",
    "site plan",
    "subdivision",
    "town center",
    "zone",
)


class HighlandCollector:
    name = "Highland"
    SCOPE_ID = "current-projects+planning-hearings-v1"
    current_projects_url = "https://www.highlandut.gov/229/Current-Projects"
    public_body_url = "https://www.utah.gov/pmn/sitemap/publicbody/4.html"
    notices_url = public_body_url
    MAX_NOTICE_PAGES = 8

    def collect(self, session: requests.Session | None = None) -> CollectionResult:
        session = session or new_session()

        projects_response = session.get(self.current_projects_url, timeout=45)
        projects_response.raise_for_status()
        permits = self.parse_current_projects(projects_response.text, projects_response.url)

        errors: list[str] = []
        try:
            notices_response = session.get(self.public_body_url, timeout=45)
            notices_response.raise_for_status()
            notice_urls = self.discover_public_hearing_urls(notices_response.text, notices_response.url)
            for notice_url in notice_urls[: self.MAX_NOTICE_PAGES]:
                try:
                    notice = session.get(notice_url, timeout=45)
                    notice.raise_for_status()
                    permits.extend(self.parse_notice_page(notice.text, notice.url))
                except Exception as exc:
                    errors.append(f"{type(exc).__name__}: {exc}")
        except Exception as exc:
            errors.append(f"{type(exc).__name__}: {exc}")

        by_key: dict[str, Permit] = {}
        for permit in permits:
            old = by_key.get(permit.key)
            if old is None or (permit.issued_date or "") > (old.issued_date or ""):
                by_key[permit.key] = permit
        permits = sorted(
            by_key.values(),
            key=lambda p: (p.issued_date or "", p.project_name or ""),
            reverse=True,
        )
        if not permits:
            detail = "; ".join(errors) if errors else "no current projects or project-specific hearings parsed"
            raise RuntimeError(f"Highland development sources returned no usable records: {detail}")

        dated = [p.issued_date for p in permits if p.issued_date]
        newest = max(dated) if dated else "unknown"
        inventory_count = sum(1 for p in permits if p.raw.get("source_kind") == "current_projects")
        hearing_count = sum(1 for p in permits if p.raw.get("source_kind") == "public_hearing")
        note = (
            "Official Highland City Current Projects inventory plus Utah Public Notice Planning Commission hearings; "
            f"{inventory_count} current project row(s), {hearing_count} project-specific hearing item(s), "
            f"latest dated activity {newest}; City project statuses/next steps are retained as development intelligence "
            "but are not treated as issued building permits"
        )
        if errors:
            note += f"; {len(errors)} hearing source request(s) unavailable"

        return CollectionResult(
            self.name,
            permits,
            self.current_projects_url,
            note,
            scope_id=self.SCOPE_ID,
        )

    @classmethod
    def parse_current_projects(cls, html: str, source_url: str) -> list[Permit]:
        soup = BeautifulSoup(html, "html.parser")
        rows: list[Permit] = []

        for table in soup.find_all("table"):
            headers = [cls._clean(th.get_text(" ", strip=True)).lower() for th in table.find_all("th")]
            joined_headers = " | ".join(headers)
            if "project name" not in joined_headers or "status" not in joined_headers or "next steps" not in joined_headers:
                continue

            for tr in table.find_all("tr"):
                cells = [cls._clean(td.get_text(" ", strip=True)) for td in tr.find_all("td")]
                if len(cells) < 6:
                    continue
                name_type, purpose, address, began, status, next_steps = cells[:6]
                if not name_type or not purpose:
                    continue

                stable = re.sub(r"\s+", " ", name_type).strip()
                digest = hashlib.sha1(stable.lower().encode("utf-8")).hexdigest()[:12].upper()
                activity_date = cls._status_date(status)
                units = cls._units(purpose)

                rows.append(
                    Permit(
                        state="UT",
                        jurisdiction=cls.name,
                        permit_number=f"HIG-PROJ-{digest}",
                        issued_date=activity_date or "",
                        permit_type=cls._permit_type(f"{name_type} {purpose}"),
                        address=address,
                        project_name=stable,
                        units=units,
                        status=next_steps or status or "Current Development Project",
                        source_name="Highland City Current Projects",
                        source_url=source_url,
                        raw={
                            "lead_stage": "DEVELOPMENT",
                            "source_kind": "current_projects",
                            "began": began,
                            "city_status": status,
                            "next_steps": next_steps,
                            "purpose_and_zoning": purpose,
                            "date_semantics": "latest_status_date_when_present",
                        },
                    )
                )
        return rows

    @classmethod
    def discover_public_hearing_urls(cls, html: str, source_url: str) -> list[str]:
        soup = BeautifulSoup(html, "html.parser")
        found: list[str] = []
        seen: set[str] = set()
        for anchor in soup.find_all("a", href=True):
            href = anchor.get("href", "")
            if "/pmn/sitemap/notice/" not in href:
                continue
            text = cls._clean(" ".join(anchor.stripped_strings)).lower()
            if "public hearing" not in text or "cancel" in text:
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
        event_date = cls._event_date(text)
        description = cls._description(text)
        if not event_date or not description:
            return []

        body_match = re.search(
            r"(?:regarding the following:|regarding:|consider and receive comments regarding the following:)\s*(.*?)(?:Any person may provide comments|The meeting agenda|For more information|$)",
            description,
            flags=re.I,
        )
        body = cls._clean(body_match.group(1)) if body_match else description
        parts = [cls._clean(part) for part in re.split(r"\s+-\s+", body) if cls._clean(part)]
        if len(parts) == 1 and body.startswith("-"):
            parts = [cls._clean(body.lstrip("- "))]

        permits: list[Permit] = []
        for item in parts:
            normalized = item.lower()
            if not any(signal in normalized for signal in DEVELOPMENT_SIGNALS):
                continue
            units = cls._units(item)
            address = cls._address(item)
            stable = cls._hearing_title(item, address)
            digest = hashlib.sha1(stable.lower().encode("utf-8")).hexdigest()[:12].upper()
            permits.append(
                Permit(
                    state="UT",
                    jurisdiction=cls.name,
                    permit_number=f"HIG-HEAR-{digest}",
                    issued_date=event_date,
                    permit_type=cls._permit_type(item),
                    address=address,
                    project_name=stable,
                    units=units,
                    status="Planning Commission Public Hearing",
                    source_name="Utah Public Notice - Highland Planning Commission",
                    source_url=source_url,
                    raw={
                        "lead_stage": "PLANNING",
                        "source_kind": "public_hearing",
                        "hearing_date": event_date,
                        "date_semantics": "scheduled_public_hearing_date",
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

    @staticmethod
    def _status_date(value: str) -> str | None:
        matches = re.findall(r"\b(\d{1,2})[./-](\d{1,2})[./-](20\d{2})\b", value or "")
        if not matches:
            return None
        month, day, year = matches[-1]
        try:
            return datetime(int(year), int(month), int(day)).date().isoformat()
        except ValueError:
            return None

    @staticmethod
    def _units(value: str) -> int | None:
        for pattern in (
            r"\b(\d{1,4})\s+(?:residential\s+)?(?:lots|units)\b",
            r"\b(\d{1,4})-unit\b",
        ):
            match = re.search(pattern, value or "", flags=re.I)
            if match:
                return int(match.group(1))
        return None

    @staticmethod
    def _permit_type(value: str) -> str:
        lowered = value.lower()
        if "site plan" in lowered:
            return "Planning Site Plan"
        if "preliminary plat" in lowered:
            return "Planning Preliminary Plat"
        if "final plat" in lowered or "subdivision" in lowered or " residential lots" in lowered:
            return "Planning Subdivision/Plat"
        if "development agreement" in lowered:
            return "Planning Development Agreement"
        if "commercial" in lowered or "office" in lowered or "assisted living" in lowered:
            return "Planning Commercial Development"
        return "Planning Development Review"

    @classmethod
    def _address(cls, value: str) -> str:
        match = re.search(
            r"\b\d{2,5}\s+(?:W(?:est)?|E(?:ast)?|N(?:orth)?|S(?:outh)?)\s+[A-Za-z0-9 .'-]+?(?=,|\.|\s+Highland\b|\s+UT\b|$)",
            value or "",
            flags=re.I,
        )
        return cls._clean(match.group(0)) if match else ""

    @classmethod
    def _hearing_title(cls, item: str, address: str) -> str:
        lowered = item.lower()
        if "skye estates" in lowered:
            return "Skye Estates Assisted Living Development Agreement"
        if "ricks" in lowered and "subdivision" in lowered:
            return "Ricks Subdivision Public Hearing"
        if address:
            return f"Highland Development Hearing - {address}"
        return cls._clean(item)[:180]
