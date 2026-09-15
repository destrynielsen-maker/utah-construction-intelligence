from __future__ import annotations

import csv
import hashlib
import io
import re
from datetime import date, datetime
from urllib.parse import urljoin

import pdfplumber
import requests
from bs4 import BeautifulSoup

from .base import CollectionResult, new_session
from ..models import Permit


DATE_RE = re.compile(r"^\d{1,2}/\d{1,2}/\d{4}$")
AGENDA_DATE_RE = re.compile(r"\b(\d{1,2})\.(\d{1,2})\.(20\d{2})\b")


class OremCollector:
    name = "Orem"
    SCOPE_ID = "monthly-permits+active-projects+drc-v1"
    landing_url = "https://orem.gov/buildingsafety/"
    active_projects_page = "https://orem.gov/apb/"
    active_projects_csv = "https://docs.google.com/spreadsheets/d/e/2PACX-1vSZGOL7drAPewGqBm9rRrxUs-CtmzaCR27pmPJoakGPhdJxZ1gVrUGVsbyyrpO-aFNprorxWaz953y9/pub?output=csv"
    public_notices_url = "https://orem.gov/public-notices/"

    def collect(self, session: requests.Session | None = None) -> CollectionResult:
        session = session or new_session()
        permits: list[Permit] = []
        notes: list[str] = []
        successful_sources = 0
        primary_url = self.landing_url

        # 1) Latest monthly issued-permit report. This is much smaller than the
        # cumulative year-to-date PDF and persistent storage keeps prior months.
        try:
            pdf_url = self.discover_pdf_url(session)
            response = session.get(pdf_url, timeout=60)
            response.raise_for_status()
            monthly = self.parse_pdf(response.content, pdf_url)
            permits.extend(monthly)
            primary_url = pdf_url
            latest_month = max((p.issued_date for p in monthly), default="unknown")
            notes.append(f"latest monthly permit report: {len(monthly)} rows through {latest_month}")
            successful_sources += 1
        except Exception as exc:
            notes.append(f"monthly permit report unavailable ({type(exc).__name__}: {exc})")

        # 2) Orem's published Active Projects Being Built sheet. Orem says this
        # list is updated weekly. Only explicit ground-up/new-construction rows
        # become sales leads; remodel/interior-finish noise is intentionally ignored.
        try:
            response = session.get(self.active_projects_csv, timeout=45)
            response.raise_for_status()
            active = self.parse_active_projects_csv(response.text, self.active_projects_page)
            permits.extend(active)
            primary_url = self.active_projects_page
            snapshot = max((p.issued_date for p in active), default="unknown")
            notes.append(f"active-projects sheet: {len(active)} explicit new-build leads; snapshot {snapshot}")
            successful_sources += 1
        except Exception as exc:
            notes.append(f"active-projects sheet unavailable ({type(exc).__name__}: {exc})")

        # 3) Latest Development Review Committee agenda. These rows are stored as
        # non-qualifying planning observations today, so they improve stage/freshness
        # visibility without pretending a planning review is an issued permit.
        try:
            agenda_url, agenda_date = self.discover_latest_drc_agenda(session)
            response = session.get(agenda_url, timeout=45)
            response.raise_for_status()
            planning = self.parse_drc_agenda_html(response.text, agenda_date, agenda_url)
            permits.extend(planning)
            primary_url = agenda_url
            notes.append(f"latest DRC agenda: {agenda_date}; {len(planning)} planning items")
            successful_sources += 1
        except Exception as exc:
            notes.append(f"DRC agenda unavailable ({type(exc).__name__}: {exc})")

        if successful_sources == 0:
            raise RuntimeError("All Orem public sources failed")

        return CollectionResult(
            self.name,
            permits,
            primary_url,
            "; ".join(notes),
            scope_id=self.SCOPE_ID,
        )

    def discover_pdf_url(self, session: requests.Session) -> str:
        response = session.get(self.landing_url, timeout=45)
        response.raise_for_status()
        soup = BeautifulSoup(response.text, "html.parser")
        year = str(date.today().year)
        ranked: list[tuple[int, str]] = []
        for anchor in soup.find_all("a", href=True):
            text = " ".join(anchor.stripped_strings)
            href = urljoin(self.landing_url, anchor["href"])
            lower = f"{text} {href}".lower()
            score = 0
            # Orem's "Monthly Building Permit Reports" link points directly at
            # the latest monthly report and is preferable to the cumulative YTD PDF.
            if "monthly building permit reports" in lower:
                score += 250
            if f"building permits {year}" in lower:
                score += 100
            if "building-permits" in lower or "building permits" in lower:
                score += 20
            if ".pdf" in lower:
                score += 10
            if year in lower:
                score += 5
            if score:
                ranked.append((score, href))
        if not ranked:
            raise RuntimeError("Could not discover Orem building-permit PDF")
        ranked.sort(reverse=True)
        return ranked[0][1]

    @classmethod
    def parse_active_projects_csv(cls, text: str, source_url: str) -> list[Permit]:
        rows = list(csv.reader(io.StringIO(text)))
        if not rows:
            return []
        headers = [cell.strip() for cell in rows[0]]
        if len(headers) < 4:
            raise RuntimeError(f"Unexpected Orem active-projects columns: {headers}")
        try:
            snapshot = datetime.strptime(headers[3].strip(), "%B %d, %Y").date().isoformat()
        except ValueError as exc:
            raise RuntimeError(f"Could not parse Orem active-projects snapshot date: {headers[3]!r}") from exc

        permits: list[Permit] = []
        for row in rows[1:]:
            row = row + [""] * (4 - len(row))
            project, address, description, status = (cell.strip() for cell in row[:4])
            if not project and not address:
                continue
            desc = description.lower()
            status_lower = status.lower()

            # Fail closed: only explicit ground-up categories become leads. Orem's
            # sheet is dominated by remodel/interior-finish work that we do not want.
            is_ground_up = (
                desc == "new commercial building"
                or desc in {"single family dwelling", "town homes"}
                or "new multifamily" in desc
                or "new multi-family" in desc
                or "new apartment" in desc
                or "new townhome" in desc
                or "new town home" in desc
                or "new duplex" in desc
            )
            if not is_ground_up or status_lower == "completed":
                continue

            digest = hashlib.sha1(
                f"{project}|{address}|{description}".lower().encode("utf-8")
            ).hexdigest()[:12].upper()
            permits.append(
                Permit(
                    state="UT",
                    jurisdiction="Orem",
                    permit_number=f"OREM-APB-{digest}",
                    issued_date=snapshot,
                    permit_type=description,
                    project_name=project,
                    address=address,
                    status=status or None,
                    source_name="City of Orem Active Projects Being Built",
                    source_url=source_url,
                    raw={
                        "project_name": project,
                        "address": address,
                        "description": description,
                        "construction_status": status,
                        "source_snapshot_date": snapshot,
                        "date_semantics": "source_snapshot_date",
                        "lead_stage": (
                            "PLANNING"
                            if "plan review" in status_lower
                            else "READY_TO_ISSUE"
                            if "ready to issue" in status_lower
                            else "CONSTRUCTION"
                        ),
                    },
                )
            )
        return permits

    def discover_latest_drc_agenda(self, session: requests.Session) -> tuple[str, str]:
        response = session.get(self.public_notices_url, timeout=45)
        response.raise_for_status()
        soup = BeautifulSoup(response.text, "html.parser")
        candidates: list[tuple[date, str]] = []
        for anchor in soup.find_all("a", href=True):
            text = " ".join(anchor.stripped_strings)
            lower = text.lower()
            if "development review committee" not in lower or "agenda" not in lower:
                continue
            match = AGENDA_DATE_RE.search(text)
            if not match:
                continue
            month, day, year = (int(value) for value in match.groups())
            agenda_date = date(year, month, day)
            candidates.append((agenda_date, urljoin(self.public_notices_url, anchor["href"])))
        if not candidates:
            raise RuntimeError("Could not discover latest Orem DRC agenda")
        agenda_date, agenda_url = max(candidates, key=lambda item: item[0])
        return agenda_url, agenda_date.isoformat()

    @classmethod
    def parse_drc_agenda_html(cls, html: str, agenda_date: str, source_url: str) -> list[Permit]:
        soup = BeautifulSoup(html, "html.parser")
        permits: list[Permit] = []
        seen: set[str] = set()
        planning_terms = (
            "site plan",
            "final plat",
            "preliminary plat",
            "rezone",
            "general plan",
            "conditional use",
            "annexation",
        )
        for item in soup.find_all("li"):
            text = " ".join(item.stripped_strings).strip()
            lower = text.lower()
            if not text or not any(term in lower for term in planning_terms):
                continue
            if text in seen:
                continue
            seen.add(text)
            address = ""
            match = re.search(r"located generally at\s+(.+)$", text, flags=re.I)
            if match:
                address = match.group(1).strip()
            project = re.sub(r"\s*[–—-]\s*Located generally at.*$", "", text, flags=re.I).strip()
            digest = hashlib.sha1(text.lower().encode("utf-8")).hexdigest()[:12].upper()
            permits.append(
                Permit(
                    state="UT",
                    jurisdiction="Orem",
                    permit_number=f"OREM-DRC-{digest}",
                    issued_date=agenda_date,
                    permit_type="Planning Review",
                    project_name=project,
                    address=address,
                    status="Under Plan Review",
                    source_name="City of Orem Development Review Committee",
                    source_url=source_url,
                    raw={
                        "agenda_item": text,
                        "agenda_date": agenda_date,
                        "date_semantics": "planning_agenda_date",
                        "lead_stage": "PLANNING",
                    },
                )
            )
        return permits

    @classmethod
    def parse_pdf(cls, content: bytes, source_url: str) -> list[Permit]:
        permits: list[Permit] = []
        with pdfplumber.open(io.BytesIO(content)) as pdf:
            for page in pdf.pages:
                for line in cls._group_lines(page.extract_words()):
                    if not line:
                        continue
                    date_text = cls._segment(line, 0, 95)
                    if not DATE_RE.match(date_text):
                        continue
                    number = cls._segment(line, 95, 145)
                    permit_type = cls._segment(line, 145, 244)
                    builder = cls._segment(line, 244, 382)
                    address = cls._segment(line, 382, 500)
                    valuation_text = cls._segment(line, 500, None)
                    if not number or not permit_type:
                        continue
                    permits.append(
                        Permit(
                            state="UT",
                            jurisdiction="Orem",
                            permit_number=number,
                            issued_date=cls._iso_date(date_text),
                            permit_type=permit_type,
                            contractor=builder or None,
                            address=address,
                            valuation=cls._money(valuation_text),
                            source_name="City of Orem Building Permit Statistics",
                            source_url=source_url,
                            raw={
                                "date": date_text,
                                "permit_number": number,
                                "permit_type": permit_type,
                                "builder": builder,
                                "site_address": address,
                                "valuation": valuation_text,
                                "date_semantics": "permit_issued_date",
                                "lead_stage": "PERMITTED",
                            },
                        )
                    )
        return permits

    @staticmethod
    def _group_lines(words: list[dict]) -> list[list[dict]]:
        lines: list[list[dict]] = []
        for word in sorted(words, key=lambda w: (w["top"], w["x0"])):
            for line in lines:
                if abs(line[0]["top"] - word["top"]) <= 1.0:
                    line.append(word)
                    break
            else:
                lines.append([word])
        return [sorted(line, key=lambda w: w["x0"]) for line in lines]

    @staticmethod
    def _segment(line: list[dict], left: float, right: float | None) -> str:
        return " ".join(
            w["text"] for w in line
            if w["x0"] >= left and (right is None or w["x0"] < right)
        ).strip()

    @staticmethod
    def _iso_date(value: str) -> str:
        month, day, year = (int(part) for part in value.split("/"))
        return date(year, month, day).isoformat()

    @staticmethod
    def _money(value: str) -> float | None:
        cleaned = value.replace("$", "").replace(",", "").strip()
        try:
            return float(cleaned) if cleaned else None
        except ValueError:
            return None
