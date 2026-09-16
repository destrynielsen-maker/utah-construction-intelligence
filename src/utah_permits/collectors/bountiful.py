from __future__ import annotations

import hashlib
import io
import re
from datetime import datetime
from urllib.parse import urljoin

import pdfplumber
import requests
from bs4 import BeautifulSoup

from .base import CollectionResult, new_session
from ..models import Permit


DEVELOPMENT_SIGNALS = (
    "site plan",
    "architectural",
    "plat approval",
    "preliminary plat",
    "final plat",
    "subdivision",
    "zone change",
    "rezone",
    "zoning map amendment",
    "development plan",
    "planned unit development",
    "pud",
    "conditional use permit",
)

POLICY_ONLY_SIGNALS = (
    "text amendment",
    "code amendment",
    "land use code",
    "zoning ordinance",
    "parking ordinance",
    "annual meeting schedule",
    "general plan update",
    "election of chair",
    "election of chairperson",
)

LOW_VALUE_SIGNALS = (
    "home occupation",
    "sign permit",
    "variance request",
    "wall and gate",
    "fence",
)

ADMIN_SIGNALS = (
    "welcome",
    "meeting minutes",
    "director's report",
    "directors report",
    "miscellaneous items",
    "adjourn",
)


class BountifulCollector:
    name = "Bountiful"
    SCOPE_ID = "civicplus-planning-agendas-v1"
    agenda_center_url = "https://www.bountiful.gov/agendacenter"
    rss_url = "https://www.bountiful.gov/RSSFeed.aspx?CID=Planning-Commission-6&ModID=65"
    notices_url = agenda_center_url
    MAX_AGENDAS = 6
    MAX_PDF_PAGES = 2
    MAX_AGENDA_BYTES = 32_000_000

    def collect(self, session: requests.Session | None = None) -> CollectionResult:
        session = session or new_session()
        agenda_urls: list[str] = []
        errors: list[str] = []

        try:
            rss = session.get(self.rss_url, timeout=30)
            rss.raise_for_status()
            agenda_urls = self.discover_agenda_urls(rss.text, rss.url)
        except Exception as exc:
            errors.append(f"rss: {type(exc).__name__}: {exc}")

        if not agenda_urls:
            try:
                center = session.get(self.agenda_center_url, timeout=30)
                center.raise_for_status()
                agenda_urls = self.discover_agenda_urls(center.text, center.url)
            except Exception as exc:
                errors.append(f"agenda center: {type(exc).__name__}: {exc}")

        permits: list[Permit] = []
        errors_by_agenda: list[str] = []
        agendas_read = 0
        for agenda_url in agenda_urls[: self.MAX_AGENDAS]:
            event_date = self._date_from_url(agenda_url)
            if not event_date:
                continue
            try:
                agenda = session.get(agenda_url, timeout=45)
                agenda.raise_for_status()
                if len(agenda.content) > self.MAX_AGENDA_BYTES:
                    raise RuntimeError(f"agenda exceeds {self.MAX_AGENDA_BYTES} byte ceiling")
                text = self._document_text(agenda)
                permits.extend(self.parse_agenda_text(text, agenda.url, event_date))
                agendas_read += 1
            except Exception as exc:
                errors_by_agenda.append(f"agenda {event_date}: {type(exc).__name__}: {exc}")

        errors.extend(errors_by_agenda)
        permits = self._dedupe(permits)
        if not permits:
            detail = "; ".join(errors) if errors else "no project-specific planning items parsed"
            raise RuntimeError(f"Bountiful planning source returned no usable records: {detail}")

        newest = max(p.issued_date for p in permits)
        note = (
            "Official Bountiful CivicPlus Planning Commission Agenda Center/RSS; "
            f"{len(permits)} project-specific planning/development item(s) from {agendas_read} recent agenda(s), "
            f"latest substantive project agenda {newest}; site plans, plats, subdivisions, zone changes and other "
            "site-specific development actions retained; policy-only, home-occupation, sign, variance and "
            "administrative items excluded; planning/development-stage intelligence only"
        )
        if errors:
            note += f"; {len(errors)} source/document error(s) encountered"

        return CollectionResult(
            self.name,
            permits,
            self.agenda_center_url,
            note,
            scope_id=self.SCOPE_ID,
        )

    @classmethod
    def discover_agenda_urls(cls, content: str, source_url: str) -> list[str]:
        soup = BeautifulSoup(content, "html.parser")
        found: list[str] = []
        seen: set[str] = set()
        is_rss = "rssfeed" in source_url.lower() or "<rss" in content.lower()

        def add(href: str) -> None:
            href = (href or "").replace("&amp;", "&").strip()
            if "/AgendaCenter/ViewFile/Agenda/" not in href:
                return
            url = urljoin(source_url, href)
            if url not in seen:
                seen.add(url)
                found.append(url)

        if is_rss:
            # The RSS feed is already category-scoped to Planning Commission.
            # CivicPlus may emit either absolute or relative document links.
            for value in re.findall(
                r"(?:https?://[^<\s\"']+)?/AgendaCenter/ViewFile/Agenda/_[0-9]{8}-[0-9]+",
                content,
                flags=re.I,
            ):
                add(value)
            for link in soup.find_all("link"):
                add(cls._clean(link.get_text(" ", strip=True)))
            for anchor in soup.find_all("a", href=True):
                add(anchor.get("href", ""))
        else:
            # Agenda Center HTML contains every city board. Select only links whose
            # visible meeting title identifies them as Planning Commission records.
            for anchor in soup.find_all("a", href=True):
                href = anchor.get("href", "")
                text = cls._clean(anchor.get_text(" ", strip=True)).lower()
                if "planning commission" not in text:
                    continue
                add(href)

        return sorted(found, key=lambda url: cls._date_from_url(url) or "", reverse=True)

    @classmethod
    def _document_text(cls, response: requests.Response) -> str:
        content_type = (response.headers.get("Content-Type") or "").lower()
        if "pdf" in content_type or response.content.startswith(b"%PDF"):
            with pdfplumber.open(io.BytesIO(response.content)) as pdf:
                pages = pdf.pages[: cls.MAX_PDF_PAGES]
                return "\n".join((page.extract_text() or "") for page in pages)
        return BeautifulSoup(response.text, "html.parser").get_text("\n", strip=True)

    @classmethod
    def parse_agenda_text(cls, text: str, source_url: str, event_date: str) -> list[Permit]:
        normalized = cls._clean(text)
        items = cls._numbered_items(normalized)
        permits: list[Permit] = []
        seen: set[str] = set()

        for item in items:
            if not cls._keep_item(item):
                continue
            permit_type = cls._permit_type(item)
            address = cls._address(item)
            project_name = cls._project_name(item, address, permit_type)
            permit_number = cls._stable_id(project_name, address, permit_type)
            if permit_number in seen:
                continue
            seen.add(permit_number)
            permits.append(
                Permit(
                    state="UT",
                    jurisdiction=cls.name,
                    permit_number=permit_number,
                    issued_date=event_date,
                    permit_type=permit_type,
                    address=address,
                    project_name=project_name,
                    status="Planning Commission Agenda Item",
                    source_name="Bountiful City Planning Commission Agenda Center",
                    source_url=source_url,
                    raw={
                        "lead_stage": "PLANNING",
                        "activity_date": event_date,
                        "date_semantics": "planning_commission_agenda_date",
                        "agenda_item": item,
                    },
                )
            )
        return permits

    @classmethod
    def _numbered_items(cls, text: str) -> list[str]:
        body = re.split(r"\bADJOURN(?:MENT)?\b", text, maxsplit=1, flags=re.I)[0]
        matches = re.finditer(
            r"(?:^|\s)(\d{1,2})\.\s+(.*?)(?=\s+\d{1,2}\.\s+|$)",
            body,
            flags=re.I,
        )
        return [cls._clean(match.group(2)) for match in matches]

    @classmethod
    def _keep_item(cls, item: str) -> bool:
        lowered = item.lower()
        if any(signal in lowered for signal in ADMIN_SIGNALS):
            return False
        if any(signal in lowered for signal in POLICY_ONLY_SIGNALS):
            return False
        if any(signal in lowered for signal in LOW_VALUE_SIGNALS):
            return False
        return any(signal in lowered for signal in DEVELOPMENT_SIGNALS)

    @staticmethod
    def _permit_type(item: str) -> str:
        lowered = item.lower()
        if "preliminary & final plat" in lowered or "preliminary and final plat" in lowered:
            return "Planning Preliminary & Final Plat"
        if "preliminary plat" in lowered:
            return "Planning Preliminary Plat"
        if "final plat" in lowered:
            return "Planning Final Plat"
        if "architectural" in lowered and "site plan" in lowered:
            return "Planning Architectural & Site Plan"
        if "site plan" in lowered:
            return "Planning Site Plan"
        if "zone change" in lowered or "rezone" in lowered or "zoning map amendment" in lowered:
            return "Planning Zone Change"
        if "conditional use permit" in lowered:
            return "Planning Conditional Use"
        if "subdivision" in lowered:
            return "Planning Subdivision"
        if "development plan" in lowered or "planned unit development" in lowered or "pud" in lowered:
            return "Planning Development Review"
        return "Planning Review"

    @classmethod
    def _project_name(cls, item: str, address: str, permit_type: str) -> str:
        match = re.search(
            r"(?:approval\s+of|review\s+for|plan\s+for|for|of)\s+(?:the\s+|a\s+|an\s+)?(.+?)\s+at\s+(?:approximately\s+)?\d",
            item,
            flags=re.I,
        )
        if match:
            value = cls._clean(match.group(1))
            value = re.sub(r"^(?:the|a|an)\s+", "", value, flags=re.I)
            if value and len(value) <= 180:
                return value
        label = permit_type.removeprefix("Planning ")
        if address:
            return f"{label} - {address}"[:180]
        return f"Bountiful {label}"[:180]

    @classmethod
    def _address(cls, item: str) -> str:
        patterns = (
            r"\bat\s+(?:approximately\s+)?(\d{1,6}\s+(?:North|South|East|West|N|S|E|W)?\s*\d{1,6}\s+(?:North|South|East|West|N|S|E|W))\b",
            r"\b(\d{1,6}\s+(?:North|South|East|West|N|S|E|W)\s*\d{1,6}\s+(?:North|South|East|West|N|S|E|W))\b",
        )
        for pattern in patterns:
            match = re.search(pattern, item, flags=re.I)
            if match:
                return cls._clean(match.group(1))
        return ""

    @staticmethod
    def _date_from_url(url: str) -> str | None:
        match = re.search(r"_([01]\d)([0-3]\d)(\d{4})-", url)
        if not match:
            return None
        try:
            month, day, year = match.groups()
            return datetime.strptime(f"{year}-{month}-{day}", "%Y-%m-%d").date().isoformat()
        except ValueError:
            return None

    @staticmethod
    def _clean(value: str) -> str:
        return re.sub(r"\s+", " ", value or "").strip(" .")

    @classmethod
    def _stable_id(cls, project_name: str, address: str, permit_type: str) -> str:
        seed = "|".join(
            part for part in (cls._clean(project_name).lower(), cls._clean(address).lower(), permit_type.lower()) if part
        )
        digest = hashlib.sha1(seed.encode("utf-8")).hexdigest()[:12].upper()
        return f"BOU-PLAN-{digest}"

    @classmethod
    def _dedupe(cls, permits: list[Permit]) -> list[Permit]:
        by_key: dict[str, Permit] = {}
        for permit in permits:
            old = by_key.get(permit.permit_number)
            if old is None or permit.issued_date > old.issued_date:
                by_key[permit.permit_number] = permit
        return sorted(by_key.values(), key=lambda p: (p.issued_date, p.project_name or ""), reverse=True)
