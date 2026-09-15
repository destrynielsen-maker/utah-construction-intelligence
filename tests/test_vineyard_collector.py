from __future__ import annotations

import unittest

from utah_permits.classify import classify_permit
from utah_permits.collectors.vineyard import VineyardCollector


class VineyardCollectorTests(unittest.TestCase):
    def test_notice_page_keeps_project_items_and_excludes_policy(self) -> None:
        html = """
        <html><body>
        Event Start Date &amp; Time September 2, 2026 07:00 PM
        Description/Agenda
        5.2. Public Hearing - To Consider Ordinance 2026-11 for compliance to Senate Bill 284
        5.3. PLAN26-0013 Conditional Use Permit - Family Entertainment (Coin-Operated Arcade Games)
        5.4. PLAN25-0003 Site Plan Application - 1600 North Office Vineyard Properties of Utah
        6. WORK SESSION
        Notice of Special Accommodations
        </body></html>
        """
        permits = VineyardCollector.parse_notice_page(html, "https://example.test/notice/1")

        self.assertEqual(2, len(permits))
        by_code = {p.raw["project_code"]: p for p in permits}
        self.assertIn("PLAN26-0013", by_code)
        self.assertIn("PLAN25-0003", by_code)
        self.assertEqual("2026-09-02", by_code["PLAN25-0003"].issued_date)
        self.assertEqual("Planning Site Plan", by_code["PLAN25-0003"].permit_type)
        self.assertEqual("1600 North Office Vineyard Properties of Utah", by_code["PLAN25-0003"].address)

        for permit in permits:
            classify_permit(permit)
            self.assertFalse(permit.qualifies)
            self.assertEqual("OTHER", permit.classification)
            self.assertEqual(0, permit.score)

    def test_cancellation_notice_is_ignored(self) -> None:
        html = """
        <html><body>
        Event Start Date &amp; Time June 17, 2026 07:00 PM
        Description/Agenda CANCELLATION NOTICE Planning Commission meeting canceled.
        Meeting Information
        </body></html>
        """
        self.assertEqual([], VineyardCollector.parse_notice_page(html, "https://example.test/notice/2"))

    def test_notice_discovery_deduplicates_and_skips_cancel_links(self) -> None:
        html = """
        <html><body>
        <a href="/pmn/sitemap/notice/1105123.html">Planning Commission Meeting</a>
        <a href="/pmn/sitemap/notice/1105123.html">Planning Commission Meeting</a>
        <a href="/pmn/sitemap/notice/1089445.html">Planning Commission Cancellation Notice</a>
        </body></html>
        """
        urls = VineyardCollector.discover_notice_urls(html, "https://www.utah.gov/pmn/sitemap/publicbody/531.html")
        self.assertEqual(["https://www.utah.gov/pmn/sitemap/notice/1105123.html"], urls)


if __name__ == "__main__":
    unittest.main()
