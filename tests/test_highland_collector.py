from __future__ import annotations

import unittest

from utah_permits.classify import classify_permit
from utah_permits.collectors.highland import HighlandCollector


class HighlandCollectorTests(unittest.TestCase):
    def test_current_projects_parses_inventory_without_promoting_to_permits(self) -> None:
        html = """
        <table>
          <tr>
            <th>Project Name and Type</th><th>Purpose and Zoning</th><th>Address</th>
            <th>Began</th><th>Status</th><th>Next Steps</th>
          </tr>
          <tr>
            <td>Ridgeview Plat N Subdivision</td><td>22 residential lots (Ridgeview PD)</td>
            <td>10000 N 5000 W</td><td>2025</td><td>Final Plat Approved 5.22.2025</td><td>Construction</td>
          </tr>
          <tr>
            <td>Ten 700 (Apple Creek) Site Plan</td><td>2 commercial buildings (Apple Creek PD)</td>
            <td>10779 N Oslo Dr.</td><td>2026</td><td>Site Plan Submitted 01.20.2026</td><td>Site Plan Under Review</td>
          </tr>
        </table>
        """
        permits = HighlandCollector.parse_current_projects(html, HighlandCollector.current_projects_url)
        self.assertEqual(2, len(permits))

        by_name = {p.project_name: p for p in permits}
        ridgeview = by_name["Ridgeview Plat N Subdivision"]
        self.assertEqual(22, ridgeview.units)
        self.assertEqual("2025-05-22", ridgeview.issued_date)
        self.assertEqual("Construction", ridgeview.status)
        self.assertEqual("DEVELOPMENT", ridgeview.raw["lead_stage"])

        apple = by_name["Ten 700 (Apple Creek) Site Plan"]
        self.assertEqual("2026-01-20", apple.issued_date)
        self.assertEqual("Planning Site Plan", apple.permit_type)

        for permit in permits:
            classify_permit(permit)
            self.assertFalse(permit.qualifies)
            self.assertEqual("OTHER", permit.classification)
            self.assertEqual(0, permit.score)

    def test_public_hearing_extracts_skye_estates_assisted_living(self) -> None:
        html = """
        <html><body>
        Event Start Date &amp; Time August 25, 2026 07:00 PM
        Description/Agenda NOTICE OF HIGHLAND PLANNING COMMISSION PUBLIC HEARING
        The Highland Planning Commission will hold a public hearing to consider and receive comments regarding the following:
        - A request from Cole Cooper, on behalf of LIHAI LLC, for the City to enter into a legislative development agreement
        to approve the development of the commercial district of the Skye Estates subdivision, namely the lot located generally
        at 6571 W Grant Blvd., Highland, UT 84003. The proposal is to allow the area to be developed as an assisted living facility
        with 75 units.
        Any person may provide comments during the public hearing.
        Notice of Special Accommodations
        </body></html>
        """
        permits = HighlandCollector.parse_notice_page(html, "https://www.utah.gov/pmn/sitemap/notice/1101745.html")
        self.assertEqual(1, len(permits))
        permit = permits[0]
        self.assertEqual("2026-08-25", permit.issued_date)
        self.assertEqual("Skye Estates Assisted Living Development Agreement", permit.project_name)
        self.assertEqual(75, permit.units)
        self.assertEqual("6571 W Grant Blvd", permit.address)
        self.assertEqual("PLANNING", permit.raw["lead_stage"])
        self.assertEqual("scheduled_public_hearing_date", permit.raw["date_semantics"])

        classify_permit(permit)
        self.assertFalse(permit.qualifies)
        self.assertEqual("OTHER", permit.classification)
        self.assertEqual(0, permit.score)

    def test_public_body_discovery_keeps_hearings_and_skips_cancelled_meetings(self) -> None:
        html = """
        <a href="/pmn/sitemap/notice/1101745.html">Public Hearing</a>
        <a href="/pmn/sitemap/notice/1101746.html">Planning Commission Meeting - CANCELLED</a>
        <a href="/pmn/sitemap/notice/1091785.html">Planning Commission Meeting</a>
        """
        urls = HighlandCollector.discover_public_hearing_urls(html, HighlandCollector.public_body_url)
        self.assertEqual(["https://www.utah.gov/pmn/sitemap/notice/1101745.html"], urls)


if __name__ == "__main__":
    unittest.main()
