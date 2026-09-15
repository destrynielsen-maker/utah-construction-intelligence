from __future__ import annotations

import unittest

from utah_permits.classify import classify_permit
from utah_permits.collectors.lehi import LehiCollector


class LehiPlanningTests(unittest.TestCase):
    def test_public_hearing_parser_keeps_development_and_suppresses_noise(self):
        html = """
        <html><main>
          <p>Public hearing and consideration of Smith Development's request for approval of the River Bend Preliminary Subdivision located at approximately 1500 N 2300 W.</p>
          <p>Public hearing and consideration of Acme Architecture's request for approval of the Tech Ridge Commercial Site Plan located at 900 W Main Street.</p>
          <p>Public hearing and consideration of AT&T's request for conditional use approval of a telecommunications antenna located at 2250 N Miller Campus Drive.</p>
          <p>Public hearing and recommendation of Lehi City's request for review of the Chapter 29 Development Code Amendment.</p>
          <p>Public hearing and consideration of Jones' request for a fence exception located at 500 S Center Street.</p>
        </main></html>
        """
        rows = LehiCollector.parse_notice_html(
            html,
            "2026-09-10",
            "https://www.lehi-ut.gov/news/test/",
        )
        self.assertEqual(len(rows), 2)
        self.assertTrue(any("River Bend" in (p.project_name or "") for p in rows))
        self.assertTrue(any("Tech Ridge" in (p.project_name or "") for p in rows))
        self.assertTrue(all(p.permit_number.startswith("LEHI-PLAN-") for p in rows))
        self.assertTrue(all(p.raw["lead_stage"] == "PLANNING" for p in rows))

        for permit in rows:
            classify_permit(permit)
            self.assertFalse(permit.qualifies)
            self.assertEqual(permit.classification, "OTHER")
            self.assertEqual(permit.score, 0)

    def test_planning_key_is_stable(self):
        html = """
        <html><main><p>Public hearing and consideration of Smith Development's request for approval of the River Bend Preliminary Subdivision located at approximately 1500 N 2300 W.</p></main></html>
        """
        first = LehiCollector.parse_notice_html(html, "2026-09-10", "https://example.test/1")[0]
        second = LehiCollector.parse_notice_html(html, "2026-09-10", "https://example.test/2")[0]
        self.assertEqual(first.permit_number, second.permit_number)
        self.assertEqual(first.key, second.key)


if __name__ == "__main__":
    unittest.main()
