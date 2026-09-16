from __future__ import annotations

import unittest

from utah_permits.classify import classify_permit
from utah_permits.collectors.west_jordan import WestJordanCollector


class WestJordanCollectorTests(unittest.TestCase):
    def test_september_hearing_keeps_projects_and_rezone(self) -> None:
        html = """
        <html><body>
        Event Start Date &amp; Time September 15, 2026 06:00 PM
        Description/Agenda Planning Commission Meeting Public Hearing Notice A public hearing will be held before the West Jordan Planning Commission.
        The purpose of the hearing is to receive public comments regarding the following:
        - Carver Construction; 5577 W Leo Park Rd; Conditional Use Permit for Outside Storage and Operations; Light Manufacturing (M-1) Zone; Carver Construction (Applicant)
        - Highlands Landing North; 7592 South 5490 West; 9.4 Acres; Future Land Use Map Amendment and Rezone from RR-1-D and SC-2 to R-3-8 and SC-2; Peterson Development (Applicant)
        - The Marlowe; 3247 West Jordan Loop Lane; Preliminary Site Plan; Planned Community (P-C) Zone; Boulder Ventures (Applicant)
        If you are interested in participating in the public hearing, please visit the City website.
        Notice of Special Accommodations
        </body></html>
        """
        permits = WestJordanCollector.parse_notice_page(html, "https://www.utah.gov/pmn/sitemap/notice/1105003.html")
        self.assertEqual(3, len(permits))
        by_name = {p.project_name: p for p in permits}
        self.assertEqual("Planning Conditional Use", by_name["Carver Construction"].permit_type)
        self.assertEqual("5577 W Leo Park Rd", by_name["Carver Construction"].address)
        self.assertEqual("Planning Rezone/Plan Amendment", by_name["Highlands Landing North"].permit_type)
        self.assertEqual(9.4, by_name["Highlands Landing North"].raw["acreage"])
        self.assertEqual("Planning Site Plan", by_name["The Marlowe"].permit_type)
        self.assertEqual("2026-09-15", by_name["The Marlowe"].issued_date)

        classify_permit(by_name["Highlands Landing North"])
        self.assertFalse(by_name["Highlands Landing North"].qualifies)
        self.assertEqual("OTHER", by_name["Highlands Landing North"].classification)
        self.assertEqual(0, by_name["Highlands Landing North"].score)

    def test_august_hearing_keeps_lot_count_and_site_plan(self) -> None:
        html = """
        <html><body>
        Event Start Date &amp; Time August 18, 2026 06:00 PM
        Description/Agenda Planning Commission Meeting Public Hearing Notice. The purpose of the hearing is to receive public comments regarding the following:
        - Old Bingham Byre Subdivision; 8180 South Old Bingham Highway; Amended Subdivision (5 lots and a private lane on 1.46 acres); R-1-8C zone; Tworoose Partners LLC/Colin Jube (applicant)
        - Master Auto Tech; 1608 West 7800 South; Conditional Use Permit for vehicle Repair; CC-F Zone; Gordon Fox Racing (applicant)
        - Enclave; 3222 West 8750 South; Preliminary Site Plan; Planned Community (P-C) Zone; Enclave Townhomes (applicant)
        If you are interested in participating in the public hearing, please visit the City website.
        Notice of Special Accommodations
        </body></html>
        """
        permits = WestJordanCollector.parse_notice_page(html, "https://www.utah.gov/pmn/sitemap/notice/1099601.html")
        self.assertEqual(3, len(permits))
        by_name = {p.project_name: p for p in permits}
        self.assertEqual(5, by_name["Old Bingham Byre Subdivision"].units)
        self.assertEqual(1.46, by_name["Old Bingham Byre Subdivision"].raw["acreage"])
        self.assertEqual("Planning Site Plan", by_name["Enclave"].permit_type)

    def test_text_amendment_excluded_and_discovery_bounded(self) -> None:
        html = """
        <html><body>
        Event Start Date &amp; Time July 21, 2026 06:00 PM
        Description/Agenda Planning Commission Meeting Public Hearing Notice. The purpose of the hearing is to receive public comments regarding the following:
        - Lumina; 8399 South Dunlop Drive; Preliminary and Final Major Subdivision; Damian Mora/Garbett Homes (Applicant)
        - Immaculate Used Cars; 1390 West 9000 South; Conditional Use Permit for Motor Vehicle Sales and Services (Used); SC-2 Zone; Mike/Immaculate Used Cars (Applicant)
        - Complete Machine; 4343 West 7800 South; Conditional Use Permit (Outdoor Storage); M-1 Zone; Slade/Complete Machine (Applicant)
        - Text Amendment - Powers and Duties of Land Use Authorities and Appeal Authorities; Amending Sections 2-3-3 and 15-5-5.
        In accordance with the Americans with Disabilities Act, accommodations are available.
        Notice of Special Accommodations
        </body></html>
        """
        permits = WestJordanCollector.parse_notice_page(html, "https://www.utah.gov/pmn/sitemap/notice/1094491.html")
        self.assertEqual(3, len(permits))
        self.assertNotIn("Text Amendment", {p.project_name for p in permits})

        body = """
        <a href="/pmn/sitemap/notice/1108333.html">Notice of Planning Commission Meeting</a>
        <a href="/pmn/sitemap/notice/1105003.html">Public Hearing</a>
        <a href="/pmn/sitemap/notice/1103103.html">Public Notice</a>
        <a href="/pmn/sitemap/notice/1108401.html">Notice of Planning Commission Work Session Meeting Agenda</a>
        <a href="/pmn/sitemap/notice/1105003.html">Public Hearing</a>
        """
        urls = WestJordanCollector.discover_notice_urls(body, WestJordanCollector.public_body_url)
        self.assertEqual(
            [
                "https://www.utah.gov/pmn/sitemap/notice/1105003.html",
                "https://www.utah.gov/pmn/sitemap/notice/1103103.html",
            ],
            urls,
        )


if __name__ == "__main__":
    unittest.main()
