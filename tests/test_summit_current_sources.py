from __future__ import annotations

import unittest
from unittest.mock import patch

from utah_permits.classify import classify_permit
from utah_permits.collectors.summit_county import SummitCountyCollector


class _Page:
    def __init__(self, text: str):
        self._text = text

    def extract_text(self):
        return self._text


class _Pdf:
    def __init__(self, text: str):
        self.pages = [_Page(text)]

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, tb):
        return False


class SummitCurrentSourceTests(unittest.TestCase):
    def test_planning_agenda_extracts_project_items_without_promoting_to_permits(self):
        text = """
        AGENDA SNYDERVILLE BASIN PLANNING COMMISSION Tuesday, September 8, 2026
        1. Public comment for items not on the agenda or pending applications.
        2. Public Hearing, Possible Action regarding the Master Planned Development (MPD)
        and Rezone of Parcel SCBP-10-2AM from the Community Commercial Zone to the
        Neighborhood Mixed-Use 1 Zone. The Master Planned Development and Rezone would
        allow for a mixed-use development that includes residential and commercial space,
        located at 6417 N Pace Frontage Rd, Silver Summit; Applicant: Clive Bridgwater;
        Administrative Process. Project #25-001, 25-002, and 25-003.
        3. Public Hearing, Possible Action regarding a Plat Amendment in the Trout Creek
        Townhouses PUD; 6600 Trout Creek CT & 6598 Glenwild Dr; Parcel TCT-B & TCT-A;
        Applicant: Alliance Engineering; Project #26-069.
        4. Director Items.
        """
        with patch(
            "utah_permits.collectors.summit_county.pdfplumber.open",
            return_value=_Pdf(text),
        ):
            rows = SummitCountyCollector.parse_planning_agenda_pdf(
                b"fake",
                "2026-09-08",
                "https://summitcountyutah.gov/DocumentCenter/View/27530",
                "Snyderville Basin",
            )

        self.assertEqual(len(rows), 2)
        self.assertTrue(all(p.permit_number.startswith("SUMMIT-PLAN-") for p in rows))
        self.assertEqual(rows[0].issued_date, "2026-09-08")
        self.assertEqual(rows[0].raw["lead_stage"], "PLANNING")
        self.assertEqual(rows[0].raw["planning_district"], "Snyderville Basin")
        self.assertIn("6417 N Pace Frontage Rd", rows[0].address)
        for permit in rows:
            classify_permit(permit)
            self.assertFalse(permit.qualifies)
            self.assertEqual(permit.classification, "OTHER")

    def test_month_name_mapping(self):
        self.assertEqual(SummitCountyCollector._month_number("September"), 9)


if __name__ == "__main__":
    unittest.main()
