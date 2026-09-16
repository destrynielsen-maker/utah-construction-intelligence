from __future__ import annotations

import unittest

from utah_permits.classify import classify_permit
from utah_permits.collectors.salt_lake_city import SaltLakeCityCollector


class SaltLakeCityCollectorTests(unittest.TestCase):
    def test_current_location_specific_project_is_retained_and_nonqualifying(self) -> None:
        html = """
        <html><body>
          <a href="/planning/2026/09/15/1556-s-500-e/">
            Zoning Map and General Plan Amendment at 1556 S 500 E
            Posted on:September 15th, 2026
            Project Location: 1556 S 500 E
            Application Type: Zoning Map Amendment, General Plan Amendment
            Petition Number: PLNPCM2026-00682 &amp; PLNPCM2026-00730
          </a>
          <a href="/planning/2026/07/21/policy/">
            Planned Developments &amp; Community Benefits
            Posted on:July 21st, 2026
            Project Location: Citywide
            Application Type: Zoning Text Amendment
            Petition Number: PLNPCM2026-00611
          </a>
        </body></html>
        """
        permits = SaltLakeCityCollector.parse_page(html, SaltLakeCityCollector.landing_url)
        self.assertEqual(1, len(permits))
        permit = permits[0]
        self.assertEqual("SLC-PLAN-PLNPCM2026-00682", permit.permit_number)
        self.assertEqual("2026-09-15", permit.issued_date)
        self.assertEqual("1556 S 500 E", permit.address)
        self.assertEqual("Planning Rezone", permit.permit_type)
        self.assertEqual(
            ["PLNPCM2026-00682", "PLNPCM2026-00730"],
            permit.raw["petition_numbers"],
        )
        self.assertEqual("active_planning_open_house_posted_date", permit.raw["date_semantics"])

        classify_permit(permit)
        self.assertFalse(permit.qualifies)
        self.assertEqual("OTHER", permit.classification)
        self.assertEqual(0, permit.score)

    def test_development_projects_are_kept_while_vacation_and_landmark_only_items_are_filtered(self) -> None:
        html = """
        <html><body>
          <a href="/planning/la-esquina/">
            La Esquina Multi-Family Mixed Development
            Posted on:July 14th, 2026
            Project Location: 950 W. 1000 N.
            Application Type: Design Review
            Petition Number: PLNPCM2026-00539
          </a>
          <a href="/planning/hillside/">
            Hillside Avenue New Construction &amp; Major Alteration at approximately 56 &amp; 58 E Hillside Avenue
            Posted on:June 9th, 2026
            Project Location: 56 &amp; 58 E Hillside Avenue
            Application Type: New Construction and Major Alteration
            Petition Number: PLNHLC2026-00278
          </a>
          <a href="/planning/rio-grande/">
            Rio Grande Street Vacation at Rio Grande St, between 900 S and Montague Avenue
            Posted on:September 8th, 2026
            Project Location: Rio Grande St, between 900 S and Montague Avenue
            Application Type: Street Vacation
            Petition Number: PLNPCM2026-00684
          </a>
          <a href="/planning/gilgal/">
            Designation of Gilgal Gardens on the Local Register as a Landmark Site
            Posted on:May 5th, 2026
            Project Location: 749 E 500 S
            Application Type: Designation of a Local Landmark Site
            Petition Number: PLNHLC2026-00364
          </a>
        </body></html>
        """
        permits = SaltLakeCityCollector.parse_page(html, SaltLakeCityCollector.landing_url)
        self.assertEqual(2, len(permits))
        by_name = {p.project_name: p for p in permits}
        self.assertIn("La Esquina Multi-Family Mixed Development", by_name)
        hillside = next(p for p in permits if p.project_name.startswith("Hillside Avenue New Construction"))
        self.assertEqual("Planning Design Review", by_name["La Esquina Multi-Family Mixed Development"].permit_type)
        self.assertEqual("Planning New Construction Review", hillside.permit_type)
        self.assertEqual("56 & 58 E Hillside Avenue", hillside.address)

    def test_non_project_links_are_ignored(self) -> None:
        html = """
        <html><body>
          <a href="/planning/about/">About Online Open Houses</a>
          <a href="/planning/2026/08/report/">Monthly Report - July 2026</a>
        </body></html>
        """
        self.assertEqual([], SaltLakeCityCollector.parse_page(html, SaltLakeCityCollector.landing_url))


if __name__ == "__main__":
    unittest.main()
