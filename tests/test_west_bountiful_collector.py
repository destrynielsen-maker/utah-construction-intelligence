from __future__ import annotations

import unittest

from utah_permits.classify import classify_permit
from utah_permits.collectors.west_bountiful import WestBountifulCollector


def notice_html(date_text: str, agenda: str, title: str = "West Bountiful Planning Commission Meeting") -> str:
    return f"""
    <html><body>
      <h1>{title}</h1>
      <div>Entity West Bountiful Public Body Planning Commission</div>
      <div>Event Start Date & Time {date_text} 07:30 PM</div>
      <div>Description/Agenda {agenda}</div>
      <div>Notice of Special Accommodations (ADA)</div>
    </body></html>
    """


class WestBountifulCollectorTests(unittest.TestCase):
    def test_discovery_keeps_planning_notices_and_skips_cancelled(self):
        html = """
        <html><body>
          <a href="/pmn/sitemap/notice/1100408.html">West Bountiful Planning Commission Meeting</a>
          <a href="/pmn/sitemap/notice/1090413.html">West Bountiful Planning Commission Meeting - Canceled</a>
          <a href="/pmn/sitemap/notice/999.html">Public Hearing - Detached Accessory Dwelling Units Code</a>
        </body></html>
        """
        urls = WestBountifulCollector.discover_notice_urls(
            html, "https://www.utah.gov/pmn/sitemap/publicbody/1554.html"
        )
        self.assertEqual(
            [
                "https://www.utah.gov/pmn/sitemap/notice/1100408.html",
                "https://www.utah.gov/pmn/sitemap/notice/999.html",
            ],
            urls,
        )

    def test_august_11_keeps_pope_and_winco_projects(self):
        agenda = (
            "1. Confirm Agenda "
            "2. Pope Subdivision Flag Lot Conditional Use Permit Revision - 1192 W 400 N. "
            "3. Conditional Use Permit - WinCo Foods LLC - 190 South 500 West. "
            "4. A-1 Height Regulation Discussion. "
            "5. Approve Meeting Minutes from July 28th, 2026. 6. Staff Reports. 7. Adjourn"
        )
        permits = WestBountifulCollector.parse_notice_page(
            notice_html("August 11, 2026", agenda),
            "https://www.utah.gov/pmn/sitemap/notice/1100408.html",
        )
        self.assertEqual(2, len(permits))
        by_name = {p.project_name: p for p in permits}
        self.assertIn("Pope Subdivision Flag Lot", by_name)
        self.assertIn("WinCo Foods LLC", by_name)
        self.assertEqual("1192 W 400 N", by_name["Pope Subdivision Flag Lot"].address)
        self.assertEqual("190 South 500 West", by_name["WinCo Foods LLC"].address)
        self.assertTrue(all(p.issued_date == "2026-08-11" for p in permits))

    def test_february_keeps_business_cup_and_belmont_preliminary_plat(self):
        agenda = (
            "1. Confirm Agenda "
            "2. Conditional Use Permit - Gameday Men's Health "
            "3. Public Hearing - Proposed Code Updates Referencing the Utah Land Use, Development and Management Act. "
            "4. Consider Proposed Code Updates Referencing the Utah Land Use, Development and Management Act Recommendation. "
            "5. Consider Preliminary Plat for Belmont Farms 2A. "
            "6. Approve Meeting Minutes from January 27th, 2026. 7. Staff Reports. 8. Adjourn."
        )
        permits = WestBountifulCollector.parse_notice_page(
            notice_html("February 10, 2026", agenda),
            "https://www.utah.gov/pmn/sitemap/notice/1057973.html",
        )
        self.assertEqual(2, len(permits))
        names = {p.project_name for p in permits}
        self.assertIn("Gameday Men's Health", names)
        self.assertIn("Belmont Farms 2A", names)
        by_name = {p.project_name: p for p in permits}
        self.assertEqual("Planning Preliminary Plat", by_name["Belmont Farms 2A"].permit_type)

    def test_policy_only_august_25_agenda_returns_no_projects(self):
        agenda = (
            "1. Confirm Agenda 2. Public Hearing - A-1 Height Regulations Code Change. "
            "3. Consider Recommendation for A-1 Height Regulations Code Change. "
            "4. Detached Accessory Dwelling Units Discussion. 5. Appeal Authority Discussion. "
            "6. Approve Meeting Minutes from August 11th, 2026. 7. Staff Reports. 8. Adjourn."
        )
        permits = WestBountifulCollector.parse_notice_page(
            notice_html("August 25, 2026", agenda),
            "https://www.utah.gov/pmn/sitemap/notice/1103675.html",
        )
        self.assertEqual([], permits)

    def test_cancelled_notice_is_ignored(self):
        html = notice_html(
            "June 23, 2026",
            "THE PLANNING COMMISSION MEETING FOR TUESDAY, JUNE 23RD, 2026 IS CANCELED.",
            title="West Bountiful Planning Commission Meeting - Canceled",
        )
        permits = WestBountifulCollector.parse_notice_page(
            html, "https://www.utah.gov/pmn/sitemap/notice/1090413.html"
        )
        self.assertEqual([], permits)

    def test_planning_rows_never_qualify_as_issued_permits(self):
        agenda = "1. Confirm Agenda 2. Conditional Use Permit - WinCo Foods LLC - 190 South 500 West. 3. Adjourn."
        permits = WestBountifulCollector.parse_notice_page(
            notice_html("August 11, 2026", agenda),
            "https://www.utah.gov/pmn/sitemap/notice/1100408.html",
        )
        self.assertEqual(1, len(permits))
        classified = classify_permit(permits[0])
        self.assertFalse(classified.qualifies)
        self.assertEqual("OTHER", classified.classification)
        self.assertEqual(0, classified.score)


if __name__ == "__main__":
    unittest.main()
