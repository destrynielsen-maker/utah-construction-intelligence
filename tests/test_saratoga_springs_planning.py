from __future__ import annotations

import unittest

from utah_permits.classify import classify_permit
from utah_permits.collectors.saratoga_springs import SaratogaSpringsCollector


class SaratogaSpringsPlanningTests(unittest.TestCase):
    def test_pending_updated_items_are_parsed_and_approved_items_are_excluded(self) -> None:
        html = """
        <html><body>
          <h2>Pending Applications</h2>
          <ol>
            <li><a href="/DocumentCenter/View/1">Pelican Point Rezone</a>, Planner: S. Stout (updated September 2026)</li>
            <li>Northshore Commercial Site Plan, Planner: K. Black (updated August 2026)</li>
          </ol>
          <h2>Approved Applications</h2>
          <ol>
            <li>Fox Hollow N4 Site Plan and Final Plat, Planner: A. Roy (approved March 2026)</li>
          </ol>
        </body></html>
        """

        permits = SaratogaSpringsCollector.parse_page(
            html,
            "https://www.saratogasprings-ut.gov/229/Applications-Pending-Recently-Approved",
        )

        self.assertEqual(2, len(permits))
        self.assertEqual("2026-09-01", permits[0].issued_date)
        self.assertEqual("Pelican Point Rezone", permits[0].project_name)
        self.assertEqual("PLANNING", permits[0].raw["lead_stage"])
        self.assertTrue(permits[0].source_url.endswith("/DocumentCenter/View/1"))
        self.assertEqual("Commercial", permits[1].raw["application_category"])

    def test_city_month_typo_is_tolerated(self) -> None:
        html = """
        <html><body><ol>
          <li>Lake Mountain Project, Planner: A. Roy (updated Augusts 2026)</li>
        </ol></body></html>
        """
        permit = SaratogaSpringsCollector.parse_page(html, "https://example.test/source")[0]
        self.assertEqual("2026-08-01", permit.issued_date)

    def test_planning_records_never_qualify_as_issued_permits(self) -> None:
        html = """
        <html><body><ol>
          <li>New Commercial Building Rezone, Planner: S. Stout (updated September 2026)</li>
        </ol></body></html>
        """
        permit = SaratogaSpringsCollector.parse_page(html, "https://example.test/source")[0]
        classify_permit(permit)

        self.assertFalse(permit.qualifies)
        self.assertEqual("OTHER", permit.classification)
        self.assertEqual(0, permit.score)


if __name__ == "__main__":
    unittest.main()
