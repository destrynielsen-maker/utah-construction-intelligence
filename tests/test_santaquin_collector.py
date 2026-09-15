from __future__ import annotations

import unittest

from utah_permits.classify import classify_permit
from utah_permits.collectors.santaquin import SantaquinCollector


class SantaquinCollectorTests(unittest.TestCase):
    def test_drc_new_business_projects_are_parsed_and_admin_noise_is_excluded(self) -> None:
        html = """
        <html><body>
        Event Start Date &amp; Time September 8, 2026 10:00 AM
        Description/Agenda
        DEVELOPMENT REVIEW COMMITTEE Tuesday, September 08, 2026, at 10:00 AM
        AGENDA NEW BUSINESS
        1. Sunset Ridge Preliminary
        2. Santaquin Veterinary Clinic
        3. Bella Vista Phase 3
        4. Bella Vista Phase 4
        5. Development Review Committee Bylaws Approval
        MEETING MINUTES APPROVAL
        6. Meeting Minutes Approval - August 25, 2026
        ADJOURNMENT
        Notice of Special Accommodations
        </body></html>
        """
        permits = SantaquinCollector.parse_notice_page(
            html,
            "https://www.utah.gov/pmn/sitemap/notice/1109999.html",
        )

        self.assertEqual(4, len(permits))
        names = {p.project_name for p in permits}
        self.assertEqual(
            {"Sunset Ridge Preliminary", "Santaquin Veterinary Clinic", "Bella Vista Phase 3", "Bella Vista Phase 4"},
            names,
        )
        self.assertTrue(all(p.issued_date == "2026-09-08" for p in permits))
        self.assertNotIn("Development Review Committee Bylaws", names)

        by_name = {p.project_name: p for p in permits}
        self.assertEqual("Planning Preliminary Plat", by_name["Sunset Ridge Preliminary"].permit_type)
        self.assertEqual("Planning Final Plat/Phase", by_name["Bella Vista Phase 3"].permit_type)

        for permit in permits:
            classify_permit(permit)
            self.assertFalse(permit.qualifies)
            self.assertEqual("OTHER", permit.classification)
            self.assertEqual(0, permit.score)
            self.assertEqual("PLANNING", permit.raw["lead_stage"])
            self.assertEqual("scheduled_drc_meeting_date", permit.raw["date_semantics"])

    def test_discovery_keeps_only_drc_notice_links(self) -> None:
        html = """
        <a href="/pmn/sitemap/notice/1101.html">Development Review Committee Meeting</a>
        <a href="/pmn/sitemap/notice/1101.html">Development Review Committee Meeting</a>
        <a href="/pmn/sitemap/notice/1102.html">Planning Commission Meeting</a>
        """
        urls = SantaquinCollector.discover_notice_urls(
            html,
            "https://www.utah.gov/pmn/sitemap/publicbody/2207.html",
        )
        self.assertEqual(["https://www.utah.gov/pmn/sitemap/notice/1101.html"], urls)


if __name__ == "__main__":
    unittest.main()
