from __future__ import annotations

import unittest

from utah_permits.classify import classify_permit
from utah_permits.collectors.salem import SalemCollector


class SalemCollectorTests(unittest.TestCase):
    def test_drc_notice_keeps_project_items_and_excludes_minutes_and_general_plan(self) -> None:
        html = """
        <html><body>
        <div>Event Start Date &amp; Time August 12, 2026 03:30 PM</div>
        <div>Description/Agenda
          1. Decision: DRC Minutes - August 5, 2026
          2. Decision: Salem City General Plan Update
          3. Decision: PP26-000003 New Salem 21B Preliminary Plat A
          4. Decision: FP26-000011 Arrowhead Springs Final Plat Phase 14
        </div>
        <div>Notice of Special Accommodations (ADA)</div>
        </body></html>
        """
        permits = SalemCollector.parse_notice_page(
            html,
            "https://www.utah.gov/pmn/sitemap/notice/1100268.html",
        )

        self.assertEqual(2, len(permits))
        by_code = {p.raw["project_code"]: p for p in permits}
        self.assertEqual("Planning Preliminary Plat", by_code["PP26-000003"].permit_type)
        self.assertEqual("Planning Final Plat", by_code["FP26-000011"].permit_type)
        self.assertEqual("2026-08-12", by_code["PP26-000003"].issued_date)

        for permit in permits:
            classify_permit(permit)
            self.assertFalse(permit.qualifies)
            self.assertEqual("OTHER", permit.classification)
            self.assertEqual(0, permit.score)
            self.assertEqual("PLANNING", permit.raw["lead_stage"])

    def test_code_free_development_items_are_retained_and_stable(self) -> None:
        html = """
        <html><body>
        <div>Event Start Date &amp; Time June 10, 2026 03:30 PM</div>
        <div>Description/Agenda
          1. Decision: DRC Minutes - June 3, 2026
          2. Decision: Salem Central Development Agreement
          3. Decision: Salem Central Zone Change A-1 to MU
        </div>
        <div>Meeting Information</div>
        </body></html>
        """
        permits = SalemCollector.parse_notice_page(
            html,
            "https://www.utah.gov/pmn/sitemap/notice/1086711.html",
        )
        self.assertEqual(2, len(permits))
        names = {p.project_name for p in permits}
        self.assertIn("Salem Central Development Agreement", names)
        self.assertIn("Salem Central Zone Change A-1 to MU", names)
        self.assertTrue(all(p.permit_number.startswith("SAL-PLAN-") for p in permits))

    def test_public_body_discovers_only_salem_drc_notices(self) -> None:
        html = """
        <a href="/pmn/sitemap/notice/1.html">Salem City DRC 2026-08-12</a>
        <a href="/pmn/sitemap/notice/1.html">Salem City DRC 2026-08-12</a>
        <a href="/pmn/sitemap/notice/2.html">Public Notice - Planning and Zoning</a>
        """
        urls = SalemCollector.discover_notice_urls(
            html,
            "https://www.utah.gov/pmn/sitemap/publicbody/7083.html",
        )
        self.assertEqual(["https://www.utah.gov/pmn/sitemap/notice/1.html"], urls)


if __name__ == "__main__":
    unittest.main()
