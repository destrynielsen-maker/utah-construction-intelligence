from __future__ import annotations

import unittest

from utah_permits.classify import classify_permit
from utah_permits.collectors.cedar_hills import CedarHillsCollector


class CedarHillsCollectorTests(unittest.TestCase):
    def test_july_meeting_keeps_project_items_and_excludes_minutes(self) -> None:
        html = """
        <html><body>
        Event Start Date &amp; Time July 14, 2026 06:00 PM
        Description/Agenda
        PLANNING COMMISSION MEETING
        SCHEDULED ITEMS &amp; PUBLIC HEARINGS
        3. Approval of the minutes from the June 23, 2026 Planning Commission meeting
        4. Review/Recommendation and Public Hearing on amendments to Plat J2 in The Cedars at Cedar Hills Subdivision, located in the H-1 Hillside Development Zone
        5. Review/Action and Public Hearing on a Preliminary Plan for The Cedars Townhomes Plat E Phase 5 located in the H-1 Hillside Development Zone
        ADJOURNMENT 6. Adjourn.
        Notice of Special Accommodations
        </body></html>
        """
        permits = CedarHillsCollector.parse_notice_page(
            html, "https://www.utah.gov/pmn/sitemap/notice/1094673.html"
        )
        self.assertEqual(2, len(permits))
        by_name = {p.project_name: p for p in permits}
        self.assertIn("The Cedars at Cedar Hills Subdivision Plat J2 Amendment", by_name)
        self.assertIn("The Cedars Townhomes Plat E Phase 5", by_name)
        self.assertEqual("2026-07-14", by_name["The Cedars Townhomes Plat E Phase 5"].issued_date)
        self.assertEqual("Planning Townhome/Multifamily", by_name["The Cedars Townhomes Plat E Phase 5"].permit_type)

        for permit in permits:
            classify_permit(permit)
            self.assertFalse(permit.qualifies)
            self.assertEqual("OTHER", permit.classification)
            self.assertEqual(0, permit.score)

    def test_january_meeting_keeps_named_subdivision_and_skips_generic_zoning_map(self) -> None:
        html = """
        <html><body>
        Event Start Date &amp; Time January 27, 2026 06:00 PM
        Description/Agenda
        SCHEDULED ITEMS &amp; PUBLIC HEARINGS
        4. Approval of the minutes from the September 23, 2025 Planning Commission meeting
        5. Review/Recommendation and Public Hearing on amendments to Canyon Heights at Cedar Hills Subdivision Plat M located in the H-1 Hillside Development Zone
        6. Review/Recommendation and Public Hearing on amendments to the Zoning Map
        7. Review/Action on approving the 2026 Planning Commission Schedule
        ADJOURNMENT 8. Adjourn.
        Notice of Special Accommodations
        </body></html>
        """
        permits = CedarHillsCollector.parse_notice_page(
            html, "https://www.utah.gov/pmn/sitemap/notice/1054329.html"
        )
        self.assertEqual(1, len(permits))
        self.assertEqual(
            "Canyon Heights at Cedar Hills Subdivision Plat M Amendment",
            permits[0].project_name,
        )
        self.assertEqual("2026-01-27", permits[0].issued_date)

    def test_discovery_skips_schedule_and_cancelled_notices(self) -> None:
        html = """
        <a href="/pmn/sitemap/notice/1094673.html">Planning Commission Meeting</a>
        <a href="/pmn/sitemap/notice/1044547.html">Planning Commission Meeting Schedule - 2026</a>
        <a href="/pmn/sitemap/notice/1080000.html">Notice of Cancelled Planning Commission Meeting</a>
        """
        urls = CedarHillsCollector.discover_notice_urls(html, CedarHillsCollector.public_body_url)
        self.assertEqual(
            ["https://www.utah.gov/pmn/sitemap/notice/1094673.html"],
            urls,
        )


if __name__ == "__main__":
    unittest.main()
