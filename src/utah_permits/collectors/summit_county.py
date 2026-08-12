from __future__ import annotations

import io
import re
from datetime import date

import pdfplumber
import requests

from .base import CollectionResult, new_session
from ..models import Permit


DATE_RE = re.compile(r"^\d{1,2}/\d{1,2}/\d{4}$")


class SummitCountyCollector:
    name = "Summit County"
    pdf_url = "https://www.summitcountyutah.gov/558/Issued-Building-Permits"

    def collect(self, session: requests.Session | None = None) -> CollectionResult:
        session = session or new_session()
        response = session.get(self.pdf_url, timeout=60)
        response.raise_for_status()
        permits = self.parse_pdf(response.content, self.pdf_url)
        return CollectionResult(self.name, permits, self.pdf_url, "Official Summit County issued-building-permits PDF")

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
