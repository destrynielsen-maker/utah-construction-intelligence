import unittest

from utah_permits.classify import classify_permit
from utah_permits.collectors.farmington import FarmingtonCollector


class FarmingtonCollectorTests(unittest.TestCase):
    def test_city_public_notices_keep_current_projects_and_filter_policy(self):
        html = """
        <table><tr><th>Date</th><th>NOTICE</th></tr>
        <tr><td>September 17, 2026</td><td>
        NOTICE OF HEARING – Planning Commission
        – Consideration of a Schematic Subdivision and an amendment to a Project Master Plan and Development Agreement for the R1 Sage Townhomes project at approximately 1771 W 950 N (North Station Lane) for Garbett Homes.
        – Consideration of a rezone request for approximately 0.36 acres of property at 37 South 200 East for Marty Curtis. The request would allow additional residential units.
        – Multiple Amendments to Title 11, Planning and Zoning, to update provisions related to the Planning Commission based on state law requirements.
        </td></tr></table>
        """
        permits = FarmingtonCollector.parse_city_public_notices(
            html, "https://farmington.utah.gov/public-notices/"
        )
        self.assertEqual(2, len(permits))
        by_name = {p.project_name: p for p in permits}
        self.assertIn("R1 Sage Townhomes", by_name)
        self.assertEqual("1771 W 950 N (North Station Lane)", by_name["R1 Sage Townhomes"].address)
        self.assertEqual("2026-09-17", by_name["R1 Sage Townhomes"].issued_date)
        self.assertTrue(any(p.project_name.startswith("Rezone - 37 South 200 East") for p in permits))
        for permit in permits:
            classify_permit(permit)
            self.assertFalse(permit.qualifies)

    def test_pmn_notice_keeps_primrose_and_marty_curtis_but_filters_policy(self):
        html = """
        <html><body>
        Event Start Date & Time July 16, 2026 07:00 PM
        Description/Agenda NOTICE OF HEARING FARMINGTON CITY Notice is hereby given that the Farmington City Planning Commission will hold a public hearing to consider the following:
        - Special Exception for increased lot coverage at 448 West 1300 North for Richard Haws.
        - Rezone of approximately 2.8 acres of property from the AA zone to the LR zone and Consideration of Schematic Subdivision and Preliminary PUD Master Plan for the Primrose Lane Subdivision consisting of 19 single family residential lots at 44 West 1600 South and approximately 1575 South and Frontage Road.
        - Rezone of 0.36 acres of property from OTR-F to R-4-F at 37 South 200 East for Marty Curtis.
        - Multiple Amendments to Title 11, Planning and Zoning.
        Notice of Special Accommodations
        </body></html>
        """
        permits = FarmingtonCollector.parse_pmn_notice(
            html, "https://www.utah.gov/pmn/sitemap/notice/example.html"
        )
        self.assertEqual(2, len(permits))
        primrose = next(p for p in permits if "Primrose Lane Subdivision" in p.project_name)
        self.assertEqual(19, primrose.units)
        self.assertEqual(2.8, primrose.raw["acreage"])
        self.assertEqual("2026-07-16", primrose.issued_date)
        self.assertTrue(any(p.address == "37 South 200 East" for p in permits))

    def test_pmn_phoenix_way_hearing_is_retained(self):
        html = """
        <html><body>
        Event Start Date & Time September 3, 2026 07:00 PM
        Description/Agenda NOTICE OF HEARING FARMINGTON CITY Notice is hereby given that the Farmington City Planning Commission will hold a public hearing to consider the following:
        - Schematic Subdivision and Consideration of Preliminary PUD (Planned Unit Development) and Development Agreement for the Phoenix Way Subdivision at 638, 658, and 678 South Phoenix Way (650 W).
        Notice of Special Accommodations
        </body></html>
        """
        permits = FarmingtonCollector.parse_pmn_notice(
            html, "https://www.utah.gov/pmn/sitemap/notice/example2.html"
        )
        self.assertEqual(1, len(permits))
        permit = permits[0]
        self.assertIn("Phoenix Way Subdivision", permit.project_name)
        self.assertEqual("2026-09-03", permit.issued_date)
        classify_permit(permit)
        self.assertFalse(permit.qualifies)

    def test_discovery_skips_cancellation(self):
        html = """
        <a href='/pmn/sitemap/notice/1.html'>Notice &amp; Agenda</a>
        <a href='/pmn/sitemap/notice/2.html'>Notice of Hearing</a>
        <a href='/pmn/sitemap/notice/3.html'>Notice of Cancellation</a>
        """
        urls = FarmingtonCollector.discover_notice_urls(
            html, "https://www.utah.gov/pmn/sitemap/publicbody/1588.html"
        )
        self.assertEqual(2, len(urls))
        self.assertFalse(any("3.html" in url for url in urls))


if __name__ == "__main__":
    unittest.main()
