from __future__ import annotations

import hashlib
import io
import re
from datetime import date

import pdfplumber
import requests
from bs4 import BeautifulSoup

from .base import CollectionResult, new_session
from ..models import Permit


NOTICE_SCAN_RE = re.compile(
    r"(?P<month>\d{1,2})[.\-/](?P<day>\d{1,3})[.\-/](?P<year>\d{2,4})\s+"
    r"Public\s+Hearing\s*-\s*(?P<title>.+?)"
    r"(?=(?:\d{1,2}[.\-/]\d{1,3}[.\-/]\d{2,4}\s+(?:Public\s+Hearing|Public\s+Notice))"
    r"|(?:Development\s+Review\s+Committee\s+Notices\s*:)"
    r"|(?:Planning\s+Commission\s+Notices\s*:)"
    r"|(?:Board\s+of\s+Adjustment\s+Notices\s*:)"
    r"|(?:Annexation\s+Notices\s*:)"
    r"|$)",
    flags=re.I,
)

DEVELOPMENT_SIGNALS = (
    "annex",
    "business park",
    "development",
    "final plat",
    "plat",
    "rezone",
    "rezoning",
    "site plan",
    "subdivision",
    "townhome",
    "apartment",
    "mixed use",
    "mixed-use",
)


class AmericanForkCollector:
    name = "American Fork"
    SCOPE_ID = "active-projects+public-notices-v1"
    report_url = (
        "https://www.americanfork.gov/DocumentCenter/View/18060/"
        "American-Fork-City-Community-Development-Active-and-Pending-Projects"
    )
    notices_url = "https://www.americanfork.gov/1128/Public-Meetings-Notices"

    def collect(self, session: requests.Session | None = None) -> CollectionResult:
        session = session or new_session()
        permits: list[Permit] = []
        notes: list[str] = []
        report_count = 0
        notice_count = 0

        try:
            response = session.get(self.report_url, timeout=45)
            response.raise_for_status()
            report_permits = self.parse_report_pdf(response.content, response.url)
            report_count = len(report_permits)
            permits.extend(report_permits)
        except Exception as exc:  # retain fresh planning intelligence if the PDF changes
            notes.append(f"active-project report unavailable ({type(exc).__name__}: {exc})")

        try:
            response = session.get(self.notices_url, timeout=45)
            response.raise_for_status()
            notice_permits = self.parse_notices_html(response.text, response.url)
            notice_count = len(notice_permits)
            permits.extend(notice_permits)
        except Exception as exc:
            notes.append(f"public notices unavailable ({type(exc).__name__}: {exc})")

        by_key = {permit.key: permit for permit in permits}
        permits = sorted(
            by_key.values(),
            key=lambda p: (p.issued_date, p.project_name or "", p.address),
            reverse=True,
        )
        if not permits:
            detail = "; ".join(notes) or "no records parsed"
            raise RuntimeError(f"American Fork sources returned no usable records: {detail}")

        newest = max((p.issued_date for p in permits), default="unknown")
        note = (
            "Official American Fork Community Development active/pending project report plus "
            f"public development notices; {report_count} active permit/project row(s), "
            f"{notice_count} planning notice(s), newest activity {newest}. "
            "Only under-construction new/multifamily/commercial-new rows qualify as construction leads."
        )
        if notes:
            note += " " + "; ".join(notes)

        return CollectionResult(
            self.name,
            permits,
            self.notices_url,
            note,
            scope_id=self.SCOPE_ID,
        )

    @classmethod
    def parse_report_pdf(cls, content: bytes, source_url: str) -> list[Permit]:
        if not content.startswith(b"%PDF"):
            raise ValueError("American Fork active-project source is not a PDF")

        rows: list[list[str | None]] = []
        with pdfplumber.open(io.BytesIO(content)) as pdf:
            for page in pdf.pages:
                for table in page.extract_tables() or []:
                    rows.extend(table)
        return cls.parse_report_rows(rows, source_url)

    @classmethod
    def parse_report_rows(
        cls,
        rows: list[list[str | None]],
        source_url: str,
    ) -> list[Permit]:
        permits: list[Permit] = []
        seen: set[str] = set()

        for row in rows:
            cells = [cls._clean_cell(value) for value in row]
            if len(cells) < 5:
                continue
            if cells[0].lower() == "project" or cells[1].lower() == "location":
                continue

            project, location, permit_type, status, date_text = cells[:5]
            if not project or not permit_type or not status:
                continue
            activity_date = cls._parse_date(date_text)
            if not activity_date:
                continue

            stage = cls._stage(status)
            if not stage:
                continue

            digest = hashlib.sha1(
                f"{project}|{location}|{permit_type}|{activity_date}".lower().encode("utf-8")
            ).hexdigest()[:12].upper()
            permit_number = f"AF-PROJ-{digest}"
            if permit_number in seen:
                continue
            seen.add(permit_number)

            permits.append(
                Permit(
                    state="UT",
                    jurisdiction=cls.name,
                    permit_number=permit_number,
                    issued_date=activity_date,
                    permit_type=permit_type,
                    address=location,
                    project_name=project,
                    status=status,
                    source_name="American Fork Community Development Active and Pending Projects",
                    source_url=source_url,
                    raw={
                        "lead_stage": stage,
                        "date_semantics": cls._date_semantics(stage),
                        "report_status": status,
                        "report_permit_type": permit_type,
                    },
                )
            )

        return permits

    @classmethod
    def parse_notices_html(cls, html: str, source_url: str) -> list[Permit]:
        soup = BeautifulSoup(html, "html.parser")
        body = re.sub(r"\s+", " ", " ".join(soup.stripped_strings)).strip()
        permits: list[Permit] = []
        seen: set[str] = set()

        for match in NOTICE_SCAN_RE.finditer(body):
            title = re.sub(r"\s+", " ", match.group("title")).strip(" -–—")
            lowered = title.lower()
            if not any(signal in lowered for signal in DEVELOPMENT_SIGNALS):
                continue

            year = int(match.group("year"))
            if year < 100:
                year += 2000
            try:
                hearing_date = date(
                    year,
                    int(match.group("month")),
                    int(match.group("day")),
                ).isoformat()
            except ValueError:
                # Fail closed on genuinely invalid City date labels while tolerating
                # harmless zero-padding such as the City's observed "09.016.2026".
                continue

            digest = hashlib.sha1(
                f"{title}|{hearing_date}".lower().encode("utf-8")
            ).hexdigest()[:12].upper()
            permit_number = f"AF-PLAN-{digest}"
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
                    project_name=title,
                    status="Public Hearing",
                    source_name="American Fork Public Meetings & Notices",
                    source_url=source_url,
                    raw={
                        "lead_stage": "PLANNING",
                        "hearing_date": hearing_date,
                        "date_semantics": "scheduled_public_hearing_date",
                    },
                )
            )

        return sorted(permits, key=lambda p: (p.issued_date, p.project_name or ""), reverse=True)

    @staticmethod
    def _clean_cell(value: str | None) -> str:
        return re.sub(r"\s+", " ", value or "").strip()

    @staticmethod
    def _parse_date(value: str) -> str | None:
        match = re.search(r"(?P<m>\d{1,2})[-/](?P<d>\d{1,2})[-/](?P<y>\d{2,4})", value)
        if not match:
            return None
        year = int(match.group("y"))
        if year < 100:
            year += 2000
        try:
            return date(year, int(match.group("m")), int(match.group("d"))).isoformat()
        except ValueError:
            return None

    @staticmethod
    def _stage(status: str) -> str | None:
        normalized = status.lower()
        if "permit expired" in normalized or "completed" in normalized:
            return None
        if "under construction" in normalized:
            return "CONSTRUCTION"
        if "application under review" in normalized:
            return "PERMIT_REVIEW"
        if "application approved" in normalized or "pending pickup" in normalized:
            return "READY_TO_ISSUE"
        return None

    @staticmethod
    def _date_semantics(stage: str) -> str:
        return {
            "CONSTRUCTION": "construction_status_date",
            "PERMIT_REVIEW": "application_received_date",
            "READY_TO_ISSUE": "application_approved_date",
        }.get(stage, "source_activity_date")
