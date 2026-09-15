from __future__ import annotations

import unittest

from utah_permits.classify import classify_permit
from utah_permits.collectors.pleasant_grove import PleasantGroveCollector


class PleasantGroveCollectorTests(unittest.TestCase):
    def test_discovers_public_hearing_notice_links_only(self) -> None:
        html = """
        <html><body>
          <a href="/pmn/sitemap/notice/1104929.html">Planning Commission Public Hearing Notice</a>
          <a href="/pmn/sitemap/notice/1107565.html">Planning Commission Meeting Agenda</a>
          <a href="/pmn/sitemap/notice/1102359.html">Planning Commission Public Hearing Notice</a>
        </body></html>
        """
        urls = PleasantGroveCollector.discover_notice_urls(
            html, "https://www.utah.gov/pmn/sitemap/publicbody/1404.html"
        )
        self.assertEqual(
            [
                "https://www.utah.gov/pmn/sitemap/notice/1104929.html",
                "https://www.utah.gov/pmn/sitemap/notice/1102359.html",
            ],
            urls,
        )

    def test_project_specific_hearing_is_planning_only(self) -> None:
        html = """
        <html><body>
        <div>Event Start Date &amp; Time</div><div>August 27, 2026 07:00 PM</div>
        <div>Description/Agenda</div>
        <div>
        AUGUST 27, 2026 PLANNING COMMISSION PUBLIC HEARING NOTICE
        FOR THE FOLLOWING: Public Hearing: Rezone - Located at 980 West 1800 North
        (North Field Neighborhood) Public Hearing to consider the request of Braxton Rapp
        for a zone change on approximately 1.03 acres of land from the RR Zone to the R1-20 Zone.
        </div>
        <div>Notice of Special Accommodations</div>
        </body></html>
        """
        permits = PleasantGroveCollector.parse_notice_page(
            html, "https://www.utah.gov/pmn/sitemap/notice/1102359.html"
        )
        self.assertEqual(1, len(permits))
        permit = permits[0]
        self.assertEqual("2026-08-27", permit.issued_date)
        self.assertEqual("980 West 1800 North", permit.address)
        self.assertEqual("PLANNING", permit.raw["lead_stage"])
        classify_permit(permit)
        self.assertFalse(permit.qualifies)
        self.assertEqual(0, permit.score)

    def test_condominium_plat_is_retained_and_policy_text_is_excluded(self) -> None:
        project_html = """
        <html><body>
        <div>Event Start Date &amp; Time</div><div>July 6, 2026 07:00 PM</div>
        <div>Description/Agenda</div>
        <div>Public Hearing: Preliminary Subdivision Plat - Located at approx. 1000 W State St.
        (Sam White's Lane Neighborhood) Public Hearing to consider a 45-lot preliminary condominium
        subdivision plat called X Development PG Mixed Use Condominium Plat.</div>
        <div>Meeting Information</div>
        </body></html>
        """
        permits = PleasantGroveCollector.parse_notice_page(
            project_html, "https://www.utah.gov/pmn/sitemap/notice/1091883.html"
        )
        self.assertEqual(1, len(permits))
        self.assertIn("45-lot", permits[0].project_name)

        policy_html = """
        <html><body>
        <div>Event Start Date &amp; Time</div><div>September 10, 2026 07:00 PM</div>
        <div>Description/Agenda</div>
        <div>Public Hearing: Code Text Amendment - Sections 10-15-47: Accessory Apartments (City Wide)
        Public Hearing to consider revised parking requirements.</div>
        <div>Meeting Information</div>
        </body></html>
        """
        self.assertEqual(
            [],
            PleasantGroveCollector.parse_notice_page(
                policy_html, "https://www.utah.gov/pmn/sitemap/notice/1104929.html"
            ),
        )


if __name__ == "__main__":
    unittest.main()
