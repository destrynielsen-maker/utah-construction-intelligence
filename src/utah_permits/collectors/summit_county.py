from __future__ import annotations

import hashlib
import io
import re
from datetime import date
from urllib.parse import urljoin

import pdfplumber
import requests
from bs4 import BeautifulSoup

from .base import CollectionResult, new_session
from ..models import Permit


DATE_RE = re.compile(r"^\d{1,2}/\d{1,2}/\d{4}$")
EVENT_DATE_RE = re.compile(
    r"\b(January|February|March|April|May|June|July|August|September|October|November|December)\s+(\d{1,2}),\s+(20\d{2})\b"
)


class SummitCountyCollector:
    name = "Summit County"
    SCOPE_ID = "issued-permits+planning-agendas-v1"
    pdf_url = "https://www.summitcountyutah.gov/558/Issued-Building-Permits"
    calendar_url = "https://www.summitcountyutah.gov/calendar.aspx"

    def collect(self, session: requests.Session | None = None) -> CollectionResult:
        session = session or new_session()
        permits: list[Permit] = []
        notes: list[str] = []
        successful_sources = 0
        primary_url = self.pdf_url

        try:
            response = session.get(self.pdf_url, timeout=60)
            response.raise_for_status()
            issued = self.parse_pdf(response.content, self.pdf_url)
            permits.extend(issued)
            latest = max((p.issued_date for p in issued), default="unknown")
            notes.append(f"issued-permit report: {len(issued)} rows through {latest}")
            successful_sources += 1
        except Exception as exc:
            notes.append(f"issued-permit report unavailable ({type(exc).__name__}: {exc})")

        try:
            agendas = self.discover_current_planning_agendas(session)
            planning: list[Permit] = []
            for district, agenda_date, agenda_url in agendas[:4]:
                response = session.get(agenda_url, timeout=45)
                response.raise_for_status()
                planning.extend(
                    self.parse_planning_agenda_pdf(
                        response.content,
                        agenda_date,
                        agenda_url,
                        district,
                    )
                )
            permits.extend(planning)
            if agendas:
                primary_url = agendas[-1][2]
            latest_agenda = max((x[1] for x in agendas), default="unknown")
            notes.append(
                f"current planning agendas: {len(agendas)} agenda(s), "
                f"{len(planning)} project item(s), latest {latest_agenda}"
            )
            successful_sources += 1
        except Exception as exc:
            notes.append(f"planning agendas unavailable ({type(exc).__name__}: {exc})")

        if successful_sources == 0:
            raise RuntimeError("All Summit County public sources failed")

        return CollectionResult(
            self.name,
            permits,
            primary_url,
            "; ".join(notes),
            scope_id=self.SCOPE_ID,
        )

    def discover_current_planning_agendas(
        self,
        session: requests.Session,
        as_of: date | None = None,
    ) -> list[tuple[str, str, str]]:
        as_of = as_of or date.today()
        params = {
            "CID": "14",
            "month": str(as_of.month),
            "view": "list",
            "year": str(as_of.year),
        }
        response = session.get(self.calendar_url, params=params, timeout=45)
        response.raise_for_status()
        soup = BeautifulSoup(response.text, "html.parser")

        event_pages: list[tuple[str, str]] = []
        seen_pages: set[str] = set()
        for anchor in soup.find_all("a", href=True):
            title = " ".join(anchor.stripped_strings).strip()
            lower = title.lower()
            if "planning commission agenda with staff reports" not in lower:
                continue
            event_url = urljoin(response.url, anchor["href"])
            if event_url in seen_pages:
                continue
            seen_pages.add(event_url)
            district = "Eastern Summit" if "eastern summit" in lower else "Snyderville Basin"
            event_pages.append((district, event_url))

        agendas: list[tuple[str, str, str]] = []
        for district, event_url in event_pages[:4]:
            event = session.get(event_url, timeout=45)
            event.raise_for_status()
            event_soup = BeautifulSoup(event.text, "html.parser")
            event_text = " ".join(event_soup.stripped_strings)
            match = EVENT_DATE_RE.search(event_text)
            if not match:
                continue
            agenda_date = date.fromisoformat(
                f"{match.group(3)}-{self._month_number(match.group(1)):02d}-{int(match.group(2)):02d}"
            ).isoformat()
            agenda_url = None
            for anchor in event_soup.find_all("a", href=True):
                text = " ".join(anchor.stripped_strings).lower()
                href = urljoin(event.url, anchor["href"])
                if "agenda" in text and "/DocumentCenter/View/" in href:
                    agenda_url = href
                    break
            if agenda_url:
                agendas.append((district, agenda_date, agenda_url))

        if not agendas:
            raise RuntimeError("Could not discover current Summit County planning agendas")
        agendas.sort(key=lambda item: item[1])
        return agendas

    @classmethod
    def parse_planning_agenda_pdf(
        cls,
        content: bytes,
        agenda_date: str,
        source_url: str,
        district: str,
    ) -> list[Permit]:
        with pdfplumber.open(io.BytesIO(content)) as pdf:
            text = "\n".join(page.extract_text() or "" for page in pdf.pages)
        normalized = re.sub(r"\s+", " ", text).strip()
        if not normalized:
            return []

        items = re.split(r"(?=\b\d+\.\s)", normalized)
        project_terms = (
            "master planned development",
            "mixed-use",
            "mixed use",
            "rezone",
            "plat amendment",
            "preliminary plat",
            "final plat",
            "subdivision",
            "site plan",
            "conditional use",
            "development agreement",
            "townhouse",
            "townhome",
            "apartment",
            "condominium",
            "hotel",
        )
        permits: list[Permit] = []
        for item in items:
            item = item.strip()
            if not re.match(r"^\d+\.\s", item):
                continue
            lower = item.lower()
            if not any(term in lower for term in project_terms):
                continue
            if not any(signal in lower for signal in ("located", "parcel", "applicant", "project #")):
                continue

            project = re.sub(r"^\d+\.\s*", "", item).strip()
            project = re.sub(r"\s+", " ", project)
            address = ""
            address_match = re.search(
                r"located (?:at|generally at)\s+(.+?)(?:;\s*Applicant|;\s*Owner|;\s*Parcel|;\s*Administrative|\.\s*Applicant|$)",
                project,
                flags=re.I,
            )
            if address_match:
                address = address_match.group(1).strip(" .;")
            digest = hashlib.sha1(
                f"{district}|{agenda_date}|{project}".lower().encode("utf-8")
            ).hexdigest()[:12].upper()
            permits.append(
                Permit(
                    state="UT",
                    jurisdiction="Summit County",
                    permit_number=f"SUMMIT-PLAN-{digest}",
                    issued_date=agenda_date,
                    permit_type="Planning Review",
                    project_name=project[:500],
                    address=address,
                    status="Under Plan Review",
                    source_name=f"Summit County {district} Planning Commission",
                    source_url=source_url,
                    raw={
                        "agenda_item": project,
                        "agenda_date": agenda_date,
                        "date_semantics": "planning_agenda_date",
                        "lead_stage": "PLANNING",
                        "planning_district": district,
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
                    date_text = cls._segment(line, 0, 73)
                    if not DATE_RE.match(date_text):
                        continue
                    left = cls._segment(line, 73, 295)
                    match = re.match(r"^(\d+)(.*)$", left)
                    if not match:
                        continue
                    number = match.group(1)
                    project_type = match.group(2).strip()
                    area = cls._segment(line, 290, 308)
                    apn = cls._segment(line, 308, 382)
                    address = cls._segment(line, 382, None)
                    if not project_type:
                        continue
                    permits.append(
                        Permit(
                            state="UT",
                            jurisdiction="Summit County",
                            permit_number=number,
                            issued_date=cls._iso_date(date_text),
                            permit_type=project_type,
                            address=address,
                            area=area or None,
                            apn=apn or None,
                            source_name="Summit County Issued Building Permits",
                            source_url=source_url,
                            raw={
                                "date": date_text,
                                "permit_number": number,
                                "project_type": project_type,
                                "area": area,
                                "apn": apn,
                                "address": address,
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
                if abs(line[0]["top"] - word["top"]) <= 0.8:
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
    def _month_number(name: str) -> int:
        return {
            "January": 1,
            "February": 2,
            "March": 3,
            "April": 4,
            "May": 5,
            "June": 6,
            "July": 7,
            "August": 8,
            "September": 9,
            "October": 10,
            "November": 11,
            "December": 12,
        }[name]
