from __future__ import annotations

import unittest

from utah_permits.classify import classify_permit
from utah_permits.collectors.eagle_mountain import EagleMountainCollector


class EagleMountainPlanningTests(unittest.TestCase):
    def test_current_pc_notice_extracts_development_items_and_skips_policy_noise(self) -> None:
        html = """
        <html><body>
          <a href="/wp-content/uploads/2026/09/pcph.pdf">
            09.22.26 PCPH Corrigan Development Agreement, RTI Rezone,
            Wildland Urban Interface, and Archery Use
          </a>
          <a href="/audit.pdf">08.21.2026 Notice of Completion of City Audit</a>
        </body></html>
        """

        permits = EagleMountainCollector.parse_page(
            html,
            "https://eaglemountain.gov/government/city-recorder/",
        )

        self.assertEqual(2, len(permits))
        self.assertEqual(
            {"Corrigan Development Agreement", "RTI Rezone"},
            {permit.project_name for permit in permits},
        )
        self.assertTrue(all(permit.issued_date == "2026-09-22" for permit in permits))
        self.assertTrue(all(permit.raw["lead_stage"] == "PLANNING" for permit in permits))
        self.assertTrue(all(permit.source_url.endswith("/wp-content/uploads/2026/09/pcph.pdf") for permit in permits))

    def test_planning_records_never_qualify_as_issued_permits(self) -> None:
        html = """
        <html><body>
          <a href="/notice.pdf">09.22.26 PCPH New Commercial Development Agreement</a>
        </body></html>
        """
        permit = EagleMountainCollector.parse_page(html, "https://example.test/source")[0]
        classify_permit(permit)

        self.assertFalse(permit.qualifies)
        self.assertEqual("OTHER", permit.classification)
        self.assertEqual(0, permit.score)


if __name__ == "__main__":
    unittest.main()
