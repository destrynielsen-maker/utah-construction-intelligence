from __future__ import annotations

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


class OremCollector:
    name = "Orem"
    landing_url = "https://orem.gov/buildingsafety/"

    def collect(self, session: requests.Session | None = None) -> CollectionResult:
        session = session or new_session()
        pdf_url = self.discover_pdf_url(session)
        response = session.get(pdf_url, timeout=60)
        response.raise_for_status()
        permits = self.parse_pdf(response.content, pdf_url)
        return CollectionResult(self.name, permits, pdf_url, "Official City of Orem permit statistics PDF")

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
