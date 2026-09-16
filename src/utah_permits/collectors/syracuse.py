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


DEVELOPMENT_LABELS = (
    "zoning amendment",
    "rezone",
    "preliminary plat",
    "final plat",
    "revised site plan",
    "site plan",
    "conditional use permit",
    "development agreement",
    "subdivision",
)

POLICY_LABELS = (
    "text amendment",
    "ordinance amendment",
    "city code amendment",
)

LOW_VALUE_SIGNALS = (
    "electric vehicle charging",
    "charging stations",
    "existing parking",
    "sign height",
    "sign size",
    "home occupation",
    "variance",
)


class SyracuseCollector:
    name = "Syracuse"
    SCOPE_ID = "civicplus-planning-hearings-v1"
    agenda_center_url = "https://syracuseut.gov/AgendaCenter"
    notices_url = agenda_center_url
    MAX_AGENDA_DETAILS = 10
    MAX_PDF_PAGES = 1
    MAX_PDF_BYTES = 4_000_000

    def collect(self, session: requests.Session | None = None) -> CollectionResult:
        session = session or new_session()
        center = session.get(self.agenda_center_url, timeout=30)
        center.raise_for_status()
        agenda_urls = self.discover_agenda_urls(center.text, center.url)

        permits: list[Permit] = []
        errors: list[str] = []
        details_read = 0
        hearing_pdfs_read = 0

        for agenda_url in agenda_urls[: self.MAX_AGENDA_DETAILS]:
            event_date = self._date_from_url(agenda_url)
            if not event_date:
                continue
            try:
                detail = session.get(agenda_url, timeout=30)
                detail.raise_for_status()
                details_read += 1
                hearing_url = self.discover_hearing_pdf_url(detail.text, detail.url)
                if not hearing_url:
                    continue
                hearing = session.get(hearing_url, timeout=30)
                hearing.raise_for_status()
                if len(hearing.content) > self.MAX_PDF_BYTES:
                    raise RuntimeError(f"hearing PDF exceeds {self.MAX_PDF_BYTES} byte ceiling")
                text = self._pdf_text(hearing.content)
                permits.extend(self.parse_hearing_text(text, hearing.url, event_date))
                hearing_pdfs_read += 1
            except Exception as exc:
                errors.append(f"{event_date}: {type(exc).__name__}: {exc}")

        permits = self._dedupe(permits)
        if not permits:
            detail = "; ".join(errors) if errors else "no project-specific hearing items parsed"
            raise RuntimeError(f"Syracuse planning source returned no usable records: {detail}")

        newest = max(p.issued_date for p in permits)
        note = (
            "Official Syracuse CivicPlus Planning Commission Agenda Center and public-hearing notices; "
            f"{len(permits)} project-specific planning/development item(s) from {details_read} recent agenda detail page(s) "
            f"and {hearing_pdfs_read} bounded one-page hearing PDF(s), latest substantive project hearing {newest}; "
            "site-specific rezones, plats, subdivisions and ground-up site plans retained; code/text policy, revised-existing-site "
            "and EV-charging-only items excluded; planning/development-stage intelligence only"
        )
        if errors:
            note += f"; {len(errors)} detail/document error(s) encountered"

        return CollectionResult(
            self.name,
            permits,
            self.agenda_center_url,
            note,
            scope_id=self.SCOPE_ID,
        )

    @classmethod
    def discover_agenda_urls(cls, html: str, source_url: str) -> list[str]:
        soup = BeautifulSoup(html, "html.parser")
        found: list[str] = []
        seen: set[str] = set()
        for anchor in soup.find_all("a", href=True):
            href = anchor.get("href", "")
            text = cls._clean(anchor.get_text(" ", strip=True)).lower()
            if "/AgendaCenter/ViewFile/Agenda/" not in href:
                continue
            if "planning commission" not in text:
                continue
            if "cancel" in text:
                continue
            url = urljoin(source_url, href)
            if url not in seen:
                seen.add(url)
                found.append(url)
        return sorted(found, key=lambda url: cls._date_from_url(url) or "", reverse=True)

    @classmethod
    def discover_hearing_pdf_url(cls, html: str, source_url: str) -> str | None:
        soup = BeautifulSoup(html, "html.parser")
        for anchor in soup.find_all("a", href=True):
            href = anchor.get("href", "")
            text = cls._clean(anchor.get_text(" ", strip=True)).lower()
            if "/AgendaCenter/ViewFile/Item/" not in href:
                continue
            if "public hearing" not in text:
                continue
            return urljoin(source_url, href)
        return None

    @classmethod
    def _pdf_text(cls, content: bytes) -> str:
        with pdfplumber.open(io.BytesIO(content)) as pdf:
            return "\n".join((page.extract_text() or "") for page in pdf.pages[: cls.MAX_PDF_PAGES])

    @classmethod
    def parse_hearing_text(cls, text: str, source_url: str, event_date: str) -> list[Permit]:
        normalized = cls._clean(text)
        body_match = re.search(
            r"following matters?:\s*(.*?)(?:\s+Connect at\b|\s+Send written comments\b|$)",
            normalized,
            flags=re.I,
        )
        body = body_match.group(1) if body_match else normalized
        items = cls._hearing_items(body)

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
                    status="Planning Commission Public Hearing",
                    source_name="Syracuse City Planning Commission Public Hearing",
                    source_url=source_url,
                    raw={
                        "lead_stage": "PLANNING",
                        "activity_date": event_date,
                        "date_semantics": "planning_commission_hearing_date",
                        "hearing_item": item,
                    },
                )
            )
        return permits

    @classmethod
    def _hearing_items(cls, body: str) -> list[str]:
        labels = DEVELOPMENT_LABELS + POLICY_LABELS
        label_pattern = "|".join(re.escape(label) for label in labels)
        matches = list(
            re.finditer(
                rf"(?:Public Hearing:\s*)?({label_pattern})\s*[:–-]\s*",
                body,
                flags=re.I,
            )
        )
        items: list[str] = []
        for index, match in enumerate(matches):
            end = matches[index + 1].start() if index + 1 < len(matches) else len(body)
            items.append(cls._clean(f"{match.group(1)}: {body[match.end():end]}"))
        return items

    @classmethod
    def _keep_item(cls, item: str) -> bool:
        lowered = item.lower()
        if any(label in lowered for label in POLICY_LABELS):
            return False
        if "revised site plan" in lowered:
            return False
        if any(signal in lowered for signal in LOW_VALUE_SIGNALS):
            return False
        return any(label in lowered for label in DEVELOPMENT_LABELS)

    @staticmethod
    def _permit_type(item: str) -> str:
        lowered = item.lower()
        if "preliminary plat" in lowered:
            return "Planning Preliminary Plat"
        if "final plat" in lowered:
            return "Planning Final Plat"
        if "site plan" in lowered:
            return "Planning Site Plan"
        if "conditional use permit" in lowered:
            return "Planning Conditional Use"
        if "zoning amendment" in lowered or "rezone" in lowered:
            return "Planning Zone Change"
        if "development agreement" in lowered:
            return "Planning Development Review"
        if "subdivision" in lowered:
            return "Planning Subdivision"
        return "Planning Review"

    @classmethod
    def _project_name(cls, item: str, address: str, permit_type: str) -> str:
        patterns = (
            r"Preliminary Plat for\s+(.+?)\s+at\s+(?:approximately|approx\.?|app\.?)?\s*\d",
            r"Final Plat for\s+(.+?)\s+at\s+(?:approximately|approx\.?|app\.?)?\s*\d",
            r"(?:approval of|revision of)\s+(?:the\s+|a\s+)?(.+?)\s+(?:commercial\s+)?site plan(?:\s+located)?\s+at\s+(?:approximately|approx\.?|app\.?)?\s*\d",
        )
        for pattern in patterns:
            match = re.search(pattern, item, flags=re.I)
            if match:
                value = cls._clean(match.group(1))
                if value:
                    return value[:180]

        applicant = re.search(r"Request by\s+(.+?)\s+for\s+(?:a\s+)?rezone\b", item, flags=re.I)
        if applicant:
            return f"{cls._clean(applicant.group(1))} Rezone"[:180]

        label = permit_type.removeprefix("Planning ")
        if address:
            return f"{label} - {address}"[:180]
        return f"Syracuse {label}"[:180]

    @classmethod
    def _address(cls, item: str) -> str:
        match = re.search(
            r"(?:at|located at)\s+(?:approximately|approx\.?|app\.?)?\s*(\d{1,6}\s+(?:North|South|East|West|N|S|E|W)\.?\s+\d{1,6}\s+(?:North|South|East|West|N|S|E|W)\.?)",
            item,
            flags=re.I,
        )
        if not match:
            return ""
        return cls._clean(match.group(1)).replace(".", "")

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
        identity = cls._clean(address).lower() if address else cls._clean(project_name).lower()
        digest = hashlib.sha1(f"{identity}|{permit_type.lower()}".encode("utf-8")).hexdigest()[:12].upper()
        return f"SYR-PLAN-{digest}"

    @classmethod
    def _dedupe(cls, permits: list[Permit]) -> list[Permit]:
        by_key: dict[str, Permit] = {}
        for permit in permits:
            old = by_key.get(permit.permit_number)
            if old is None or permit.issued_date > old.issued_date:
                by_key[permit.permit_number] = permit
        return sorted(by_key.values(), key=lambda p: (p.issued_date, p.project_name or ""), reverse=True)
