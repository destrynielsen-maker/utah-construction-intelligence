from __future__ import annotations

import unittest

from utah_permits.classify import classify_permit
from utah_permits.collectors.alpine import AlpineCollector


class AlpineCollectorTests(unittest.TestCase):
    def test_amended_agenda_keeps_projects_and_excludes_policy_items(self) -> None:
        html = """
        <html><body>
        Event Start Date &amp; Time September 15, 2026 06:00 PM
        Description/Agenda
        ALPINE CITY PLANNING COMMISSION MEETING NOTICE
        III. ACTION/DISCUSSION ITEMS:
        A. Action Item: Public Hearing - Proposed Development Agreement for new subdivision on Healey Blvd
        B. Action Item: Alpine Fitness Commercial Site Plan Update
        C. Action Item: Public Hearing - Proposed text amendments to Alpine Development Code §3.12 Sensitive Land Ordinance and addition of Wildland-Urban Interface (WUI) map
        D. Action Item: Public Hearing - Proposed text amendments to Alpine Development Code §3.21.060 regarding Fences, Walls, and Hedges
        IV. COMMUNICATIONS
        V. APPROVAL OF PLANNING COMMISSION MINUTES
        Notice of Special Accommodations
        </body></html>
        """
        permits = AlpineCollector.parse_notice_page(
            html,
            "https://www.utah.gov/pmn/sitemap/notice/1108751.html",
        )
        self.assertEqual(2, len(permits))
        by_name = {p.project_name: p for p in permits}
        self.assertIn("Healey Blvd Subdivision Development Agreement", by_name)
        self.assertIn("Alpine Fitness Commercial Site Plan", by_name)

        healey = by_name["Healey Blvd Subdivision Development Agreement"]
        self.assertEqual("2026-09-15", healey.issued_date)
        self.assertEqual("Healey Blvd", healey.address)
        self.assertEqual("Planning Development Agreement", healey.permit_type)
        self.assertEqual("PLANNING", healey.raw["lead_stage"])
        self.assertEqual("scheduled_planning_meeting_date", healey.raw["date_semantics"])

        fitness = by_name["Alpine Fitness Commercial Site Plan"]
        self.assertEqual("Planning Site Plan", fitness.permit_type)

        for permit in permits:
            classify_permit(permit)
            self.assertFalse(permit.qualifies)
            self.assertEqual("OTHER", permit.classification)
            self.assertEqual(0, permit.score)

    def test_policy_only_agenda_returns_no_development_records(self) -> None:
        html = """
        <html><body>
        Event Start Date &amp; Time September 1, 2026 06:00 PM
        Description/Agenda
        III. ACTION/DISCUSSION ITEMS:
        A. Action Item: Proposed detached ADU code
        B. Action Item: Proposed text amendments to Alpine Development Code
        IV. COMMUNICATIONS
        Notice of Special Accommodations
        </body></html>
        """
        self.assertEqual([], AlpineCollector.parse_notice_page(html, "https://example.invalid/notice"))

    def test_notice_discovery_keeps_planning_meetings_and_skips_cancelled(self) -> None:
        html = """
        <a href="/pmn/sitemap/notice/1108751.html">9.15.26 Planning Commission Meeting Amended Packet</a>
        <a href="/pmn/sitemap/notice/1108189.html">9.15.26 Planning Commission Meeting</a>
        <a href="/pmn/sitemap/notice/1097000.html">CANCELLED - Planning Commission Meeting</a>
        <a href="/pmn/sitemap/notice/1100000.html">City Council Meeting</a>
        """
        urls = AlpineCollector.discover_notice_urls(html, AlpineCollector.public_body_url)
        self.assertEqual(
            [
                "https://www.utah.gov/pmn/sitemap/notice/1108751.html",
                "https://www.utah.gov/pmn/sitemap/notice/1108189.html",
            ],
            urls,
        )


if __name__ == "__main__":
    unittest.main()
