from __future__ import annotations

import unittest

from utah_permits.classify import classify_permit
from utah_permits.collectors.sandy import SandyCollector


class SandyCollectorTests(unittest.TestCase):
    def test_subdivision_amendment_is_planning_only(self) -> None:
        html = """
        <html><body>
        Notice of Public Meeting - Subdivision Amend
        Event Start Date &amp; Time September 21, 2026 01:30 PM
        Description/Agenda Notice of Public Meeting NOTICE IS HEREBY GIVEN that on September 21st, 2026,
        at approximately 1:30 p.m., the Sandy City Community Development Director will hold a public meeting
        regarding a final subdivision amendment submitted by Aaron Smith for the property located at 830 E 9400 S.
        Notice of Special Accommodations
        </body></html>
        """
        permits = SandyCollector.parse_notice_page(html, "https://www.utah.gov/pmn/sitemap/noticehistory/345489.html")
        self.assertEqual(1, len(permits))
        permit = permits[0]
        self.assertEqual("830 E 9400 S Final Subdivision Amendment", permit.project_name)
        self.assertEqual("2026-09-21", permit.issued_date)
        self.assertEqual("830 E 9400 S", permit.address)
        self.assertEqual("Planning Subdivision/Plat", permit.permit_type)
        self.assertEqual("scheduled_public_meeting_or_hearing_date", permit.raw["date_semantics"])

        classify_permit(permit)
        self.assertFalse(permit.qualifies)
        self.assertEqual("OTHER", permit.classification)
        self.assertEqual(0, permit.score)

    def test_indigo_subdivision_keeps_lot_count(self) -> None:
        html = """
        <html><body>
        Notice of Public Meeting - Indigo Subdivision
        Event Start Date &amp; Time July 16, 2026 06:15 PM
        Description/Agenda Notice of Public Meeting NOTICE IS HEREBY GIVEN that on July 16, 2026,
        the Sandy City Planning Commission will hold a public meeting regarding a Subdivision and Special Exception
        Application submitted by Damian Mora with Garbett Homes on the property located at 348 E 8000 S.
        The request is to subdivide the existing parcel into a 20-lot single-family home development with access onto 8000 S.
        Notice of Special Accommodations
        </body></html>
        """
        permits = SandyCollector.parse_notice_page(html, "https://www.utah.gov/pmn/sitemap/notice/1093717.html")
        self.assertEqual(1, len(permits))
        permit = permits[0]
        self.assertEqual("Indigo Subdivision", permit.project_name)
        self.assertEqual(20, permit.units)
        self.assertEqual("348 E 8000 S", permit.address)
        self.assertEqual("2026-07-16", permit.issued_date)

    def test_policy_notice_is_excluded_and_discovery_accepts_revisions(self) -> None:
        policy_html = """
        <html><body>
        Notice of Public Hearing - Proposed Code Amendment
        Event Start Date &amp; Time August 20, 2026 06:15 PM
        Description/Agenda Amendments to Title 21 of the Land Development Code related to Detached Accessory Dwelling Units (ADU).
        Notice of Special Accommodations
        </body></html>
        """
        self.assertEqual([], SandyCollector.parse_notice_page(policy_html, "https://www.utah.gov/pmn/sitemap/notice/1102128.html"))

        body = """
        <a href="/pmn/sitemap/noticehistory/345489.html">Notice of Public Meeting - Subdivision Amend</a>
        <a href="/pmn/sitemap/notice/1103000.html">Planning Commission</a>
        <a href="/pmn/sitemap/notice/1102128.html">Notice of Public Hearing - Proposed Code Amendment</a>
        <a href="/pmn/sitemap/notice/1093717.html">Notice of Public Meeting - Indigo Subdivision</a>
        <a href="/pmn/sitemap/notice/1093717.html">Notice of Public Meeting - Indigo Subdivision</a>
        """
        urls = SandyCollector.discover_notice_urls(body, SandyCollector.public_body_url)
        self.assertEqual(
            [
                "https://www.utah.gov/pmn/sitemap/noticehistory/345489.html",
                "https://www.utah.gov/pmn/sitemap/notice/1093717.html",
            ],
            urls,
        )


if __name__ == "__main__":
    unittest.main()
