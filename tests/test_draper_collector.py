from __future__ import annotations

import unittest

from utah_permits.classify import classify_permit
from utah_permits.collectors.draper import DraperCollector


class DraperCollectorTests(unittest.TestCase):
    def test_academy_plaza_notice_parses_site_plan(self) -> None:
        html = """
        <html><body>
        <h1>Notice of Public Hearing: Academy Plaza Site Plan Request</h1>
        Event Start Date &amp; Time September 24, 2026 06:30 PM
        Description/Agenda Posted on September 10, 2026. NOTICE OF PUBLIC HEARING: Academy Plaza Site Plan Request.
        Notice is hereby given that Draper City will hold a public hearing before the Planning Commission.
        The purpose of the request is to receive approval of a site plan for the development of office/warehouse and vertical mixed use buildings.
        Notice of Special Accommodations
        </body></html>
        """
        permit = DraperCollector.parse_notice_page(html, "https://www.utah.gov/pmn/sitemap/notice/1107761.html")
        self.assertIsNotNone(permit)
        assert permit is not None
        self.assertEqual("Academy Plaza Site Plan Request", permit.project_name)
        self.assertEqual("2026-09-24", permit.issued_date)
        self.assertEqual("Planning Site Plan", permit.permit_type)
        self.assertEqual("scheduled_planning_hearing_date", permit.raw["date_semantics"])

        classify_permit(permit)
        self.assertFalse(permit.qualifies)
        self.assertEqual("OTHER", permit.classification)
        self.assertEqual(0, permit.score)

    def test_ssvm_notice_keeps_applications_address_lots_and_area(self) -> None:
        html = """
        <html><body>
        <h1>Notice of Public Hearing: SSVM Development Agreement, Land Use Map Amendment, and Zoning Map Amendment Requests</h1>
        Event Start Date &amp; Time September 10, 2026 06:30 PM
        Description/Agenda Notice is hereby given that Draper City will hold a public hearing before the Planning Commission.
        The request is to allow development of the property into 4 lots on a private roadway, amend the Land Use Map,
        and amend the Zoning Map for approximately 1.58 acres of land located at 11511 S. 700 W.
        Application Nos. 2026-0126-DA, 2026-0124-MA, and 2026-0125-MA.
        Notice of Special Accommodations
        </body></html>
        """
        permit = DraperCollector.parse_notice_page(html, "https://www.utah.gov/pmn/sitemap/notice/1104609.html")
        self.assertIsNotNone(permit)
        assert permit is not None
        self.assertEqual("DRP-PLAN-2026-0126-DA", permit.permit_number)
        self.assertEqual(["2026-0126-DA", "2026-0124-MA", "2026-0125-MA"], permit.raw["application_numbers"])
        self.assertEqual("11511 S. 700 W", permit.address)
        self.assertEqual(4, permit.units)
        self.assertEqual("1.58 acres", permit.area)
        self.assertEqual("Planning Development Agreement", permit.permit_type)

        classify_permit(permit)
        self.assertFalse(permit.qualifies)
        self.assertEqual(0, permit.score)

    def test_discovery_keeps_project_notices_and_skips_agenda_and_cancelled(self) -> None:
        html = """
        <a href="/pmn/sitemap/notice/1107761.html">Notice of Public Hearing: Academy Plaza Site Plan Request</a>
        <a href="/pmn/sitemap/notice/1107763.html">Notice of Public Meeting: Grange Plat Amendment Request</a>
        <a href="/pmn/sitemap/notice/1106449.html">Planning Commission Agenda</a>
        <a href="/pmn/sitemap/notice/1109999.html">Notice of Public Hearing: Project - CANCELLED</a>
        """
        urls = DraperCollector.discover_notice_urls(html, DraperCollector.public_body_url)
        self.assertEqual(
            [
                "https://www.utah.gov/pmn/sitemap/notice/1107761.html",
                "https://www.utah.gov/pmn/sitemap/notice/1107763.html",
            ],
            urls,
        )


if __name__ == "__main__":
    unittest.main()
