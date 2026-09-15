from __future__ import annotations

import unittest

from utah_permits.classify import classify_permit
from utah_permits.collectors.orem import OremCollector


class OremCurrentSourceTests(unittest.TestCase):
    def test_active_projects_keeps_only_explicit_ground_up_noncompleted_rows(self):
        csv_text = "\n".join([
            "Name of Project,Address,Description | Late Update:,August 19, 2026",
            "Apollo Burger,452 N State Street,New Commercial Building,Under Construction",
            "Alpine Credit Union,1510 N State Street,Remodel,Near Completion",
            "RWB Warehouse,1126 N 1300 West,New Commercial Building,Completed",
            "Ace Auto,1135 N State Street,New Commercial Building,Under Plan Review",
        ])
        rows = OremCollector.parse_active_projects_csv(csv_text, "https://orem.gov/apb/")
        self.assertEqual(len(rows), 2)
        self.assertEqual({p.project_name for p in rows}, {"Apollo Burger", "Ace Auto"})
        self.assertTrue(all(p.issued_date == "2026-08-19" for p in rows))
        self.assertTrue(all(p.permit_number.startswith("OREM-APB-") for p in rows))
        self.assertEqual(next(p for p in rows if p.project_name == "Ace Auto").raw["lead_stage"], "PLANNING")
        for permit in rows:
            classify_permit(permit)
            self.assertTrue(permit.qualifies)
            self.assertEqual(permit.classification, "COMMERCIAL")

    def test_drc_agenda_rows_are_planning_observations_not_issued_permit_leads(self):
        html = """
        <html><body><ol>
          <li>Admin Site Plan – Orem Hospital OR Addition – Located generally at 331 W 400 North</li>
          <li>Site Plan – Center for Women and Children – Located generally at 866 N 300 West</li>
          <li>Minutes – Approval of prior minutes</li>
        </ol></body></html>
        """
        rows = OremCollector.parse_drc_agenda_html(html, "2026-09-14", "https://orem.gov/test-agenda/")
        self.assertEqual(len(rows), 2)
        self.assertEqual(rows[0].issued_date, "2026-09-14")
        self.assertTrue(all(p.status == "Under Plan Review" for p in rows))
        self.assertTrue(all(p.raw["lead_stage"] == "PLANNING" for p in rows))
        for permit in rows:
            classify_permit(permit)
            self.assertFalse(permit.qualifies)
            self.assertEqual(permit.classification, "OTHER")

    def test_synthetic_active_project_key_is_stable(self):
        csv_text = "\n".join([
            "Name of Project,Address,Description | Late Update:,August 19, 2026",
            "Apollo Burger,452 N State Street,New Commercial Building,Under Construction",
        ])
        first = OremCollector.parse_active_projects_csv(csv_text, "https://orem.gov/apb/")[0]
        second = OremCollector.parse_active_projects_csv(csv_text, "https://orem.gov/apb/")[0]
        self.assertEqual(first.permit_number, second.permit_number)
        self.assertEqual(first.key, second.key)


if __name__ == "__main__":
    unittest.main()
