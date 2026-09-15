from __future__ import annotations

import unittest

from utah_permits.classify import classify_permit
from utah_permits.collectors.mapleton import MapletonCollector


class MapletonCollectorTests(unittest.TestCase):
    def test_notice_parser_keeps_project_items_and_excludes_noise(self) -> None:
        html = """
        <html><body>
        <h1>Planning Commission Meeting 6-11-26</h1>
        <div>Event Start Date & Time June 11, 2026 06:00 PM</div>
        <div>Description/Agenda
        1. Planning Commission Meeting Minutes - May 28, 2026.
        2. Consideration of a Preliminary Plat application for the Mapleton Corner subdivision consisting of three lots in the A-2 (TDR-R) Zone located at 630 North 1600 East.
        3. Consideration of a Preliminary Plat application for the Harmony Ridge Plat 'K' subdivision consisting of 72 lots in the Planned Development (PD-3) Zone located at approximately 300 East 4500 South.
        4. Consideration of a Home Occupation Permit for an in-home preschool located at 952 West 1700 North.
        PUBLIC COMMENT MAY BE ACCEPTED AT THE DISCRETION OF THE CHAIR
        Notice of Special Accommodations
        </div>
        </body></html>
        """
        permits = MapletonCollector.parse_notice_page(html, "https://www.utah.gov/pmn/sitemap/notice/1086289.html")
        self.assertEqual(2, len(permits))
        by_units = {p.units: p for p in permits}
        self.assertIn(3, by_units)
        self.assertIn(72, by_units)
        self.assertEqual("630 North 1600 East", by_units[3].address)
        self.assertEqual("300 East 4500 South", by_units[72].address)
        for permit in permits:
            classify_permit(permit)
            self.assertFalse(permit.qualifies)
            self.assertEqual("OTHER", permit.classification)
            self.assertEqual("PLANNING", permit.raw["lead_stage"])

    def test_cancelled_notice_is_ignored(self) -> None:
        html = """
        <html><body>
        <div>Event Start Date & Time September 10, 2026 06:00 PM</div>
        <div>Description/Agenda PLANNING COMMISSION CANCELLATION AGENDA The meeting has been CANCELLED. Notice of Special Accommodations</div>
        </body></html>
        """
        self.assertEqual([], MapletonCollector.parse_notice_page(html, "https://example.test/cancel"))


if __name__ == "__main__":
    unittest.main()
