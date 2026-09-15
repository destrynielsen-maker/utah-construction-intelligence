from __future__ import annotations

import unittest

from utah_permits.classify import classify_permit
from utah_permits.collectors.american_fork import AmericanForkCollector


class AmericanForkTests(unittest.TestCase):
    def test_active_project_rows_keep_only_live_project_stages(self) -> None:
        rows = [
            ["Project", "Location", "Permit Type", "Status", "Date"],
            [
                "High Pointe Apartments",
                "695 East 620 South",
                "Commercial\nApartments &\nTownhomes",
                "Application under\nreview",
                "6-23-26",
            ],
            [
                "Sunline Landscapes",
                "360 East 1700 South",
                "New Commercial",
                "Under\nConstruction",
                "5-28-26",
            ],
            [
                "Edgewater Townhomes",
                "491-509 South 1110 West Lots 319-324",
                "Multifamily",
                "Under Construction",
                "4-28-26",
            ],
            [
                "IBC",
                "856 East 930 South",
                "Commercial Remodel",
                "Under Construction",
                "2-23-26",
            ],
            [
                "Autumn Crest",
                "1045 North 950 East Lot 58",
                "New Residential",
                "Completed",
                "2-25-26",
            ],
        ]

        permits = AmericanForkCollector.parse_report_rows(rows, "https://example.test/report.pdf")
        self.assertEqual(4, len(permits))
        self.assertEqual("PERMIT_REVIEW", permits[0].raw["lead_stage"])
        self.assertEqual("2026-06-23", permits[0].issued_date)

        by_project = {p.project_name: p for p in permits}
        classify_permit(by_project["High Pointe Apartments"])
        classify_permit(by_project["Sunline Landscapes"])
        classify_permit(by_project["Edgewater Townhomes"])
        classify_permit(by_project["IBC"])

        self.assertFalse(by_project["High Pointe Apartments"].qualifies)
        self.assertEqual("COMMERCIAL", by_project["Sunline Landscapes"].classification)
        self.assertTrue(by_project["Sunline Landscapes"].qualifies)
        self.assertEqual("MULTIFAMILY", by_project["Edgewater Townhomes"].classification)
        self.assertTrue(by_project["Edgewater Townhomes"].qualifies)
        self.assertFalse(by_project["IBC"].qualifies)

    def test_public_notices_keep_development_hearings_only(self) -> None:
        html = """
        <html><body>
        <p><span>09.14.2026</span><span>Public Hearing - North Pointe Business Park, Building C - Amended Final Plat</span></p>
        <p><span>08.19.2026</span><span>Public Hearing - Chipman and Stake Center 2 Annexation</span></p>
        <p><span>09.016.2026</span><span>Public Hearing - Westfields Rezone</span></p>
        <p><span>09.02.2026</span><span>Public Hearing - Chapter 12.16 Park Strips and Trees - Code Text Amendment</span></p>
        </body></html>
        """
        permits = AmericanForkCollector.parse_notices_html(html, "https://example.test/notices")

        self.assertEqual(3, len(permits))
        self.assertEqual("2026-09-16", permits[0].issued_date)
        self.assertEqual("Westfields Rezone", permits[0].project_name)
        self.assertEqual("2026-09-14", permits[1].issued_date)
        self.assertEqual("PLANNING", permits[1].raw["lead_stage"])
        for permit in permits:
            classify_permit(permit)
            self.assertFalse(permit.qualifies)
            self.assertEqual(0, permit.score)


if __name__ == "__main__":
    unittest.main()
