from __future__ import annotations

import unittest

from utah_permits.classify import classify_permit
from utah_permits.collectors.spanish_fork import SpanishForkCollector


class SpanishForkPlanningTests(unittest.TestCase):
    def test_current_projects_only_and_stable_ids(self) -> None:
        html = """
        <html><body>
          <h3>Current Projects25 documents</h3>
          <div><a href="/DocumentCenter/View/1">Anela Townhomes PP</a></div>
          <div><a href="/DocumentCenter/View/2">North Star Printing SP</a></div>
          <div><a href="/DocumentCenter/View/3">Olson Duplex ZA</a></div>
          <h3>Completed Project Applications331 documents</h3>
          <div><a href="/DocumentCenter/View/4">Rees Apartments SP</a></div>
        </body></html>
        """

        first = SpanishForkCollector.parse_projects_html(
            html,
            "https://www.spanishfork.org/current_projects.php",
            "2026-09-15",
        )
        second = SpanishForkCollector.parse_projects_html(
            html,
            "https://www.spanishfork.org/current_projects.php",
            "2026-09-16",
        )

        self.assertEqual(3, len(first))
        self.assertEqual(
            {p.project_name for p in first},
            {"Anela Townhomes", "North Star Printing", "Olson Duplex"},
        )
        self.assertEqual(
            [p.permit_number for p in first],
            [p.permit_number for p in second],
        )
        self.assertEqual("PP", next(p for p in first if p.project_name == "Anela Townhomes").raw["application_code"])
        self.assertEqual("2026-09-15", first[0].raw["source_snapshot_date"])
        self.assertTrue(all(p.raw["lead_stage"] == "PLANNING" for p in first))

    def test_spanish_fork_planning_rows_never_qualify(self) -> None:
        html = """
        <html><body>
          <h3>Current Projects</h3>
          <a href="/DocumentCenter/View/1">Anela Townhomes PP</a>
          <a href="/DocumentCenter/View/2">North Springs Business Park SP</a>
          <h3>Completed Project Applications</h3>
        </body></html>
        """
        permits = SpanishForkCollector.parse_projects_html(
            html,
            "https://example.test/current-projects",
            "2026-09-15",
        )

        for permit in permits:
            classify_permit(permit)
            self.assertFalse(permit.qualifies)
            self.assertEqual("OTHER", permit.classification)
            self.assertEqual(0, permit.score)

    def test_growth_context_is_parsed_without_creating_fake_permits(self) -> None:
        html = """
        <html><body>
          <p>All data accurate as of July 1, 2026</p>
          <table>
            <tr><td>Total Building Permits</td><td>607</td></tr>
            <tr><td>Permits for Single-family Homes</td><td>94</td></tr>
            <tr><td>Permits for Multi-unit Homes</td><td>132</td></tr>
          </table>
        </body></html>
        """
        stats = SpanishForkCollector.parse_growth_html(html)

        self.assertEqual("July 1, 2026", stats["as_of"])
        self.assertEqual(607, stats["total_building_permits"])
        self.assertEqual(94, stats["single_family_permits"])
        self.assertEqual(132, stats["multi_unit_permits"])


if __name__ == "__main__":
    unittest.main()
