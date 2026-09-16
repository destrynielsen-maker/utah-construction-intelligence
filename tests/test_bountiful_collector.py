import unittest

from utah_permits.classify import classify_permit
from utah_permits.collectors.bountiful import BountifulCollector


class BountifulCollectorTests(unittest.TestCase):
    def test_agenda_center_discovery_is_planning_only_and_newest_first(self):
        html = """
        <html><body>
        <a href="/AgendaCenter/ViewFile/Agenda/_09082026-970">City Council Regular Meeting Material</a>
        <a href="/AgendaCenter/ViewFile/Agenda/_09012026-966">Planning Commission Regular Meeting Material</a>
        <a href="/AgendaCenter/ViewFile/Agenda/_09152026-968">Planning Commission Regular Meeting Material</a>
        <a href="/AgendaCenter/ViewFile/Agenda/_08182026-962">Power Commission Regular Meeting Agenda</a>
        </body></html>
        """
        urls = BountifulCollector.discover_agenda_urls(html, "https://www.bountiful.gov/agendacenter")
        self.assertEqual(
            [
                "https://www.bountiful.gov/AgendaCenter/ViewFile/Agenda/_09152026-968",
                "https://www.bountiful.gov/AgendaCenter/ViewFile/Agenda/_09012026-966",
            ],
            urls,
        )

    def test_rss_discovery_accepts_relative_agenda_links(self):
        rss = """
        <rss><channel>
          <item><link>/AgendaCenter/ViewFile/Agenda/_06162026-862</link></item>
          <item><link>https://www.bountiful.gov/AgendaCenter/ViewFile/Agenda/_07212026-863</link></item>
        </channel></rss>
        """
        urls = BountifulCollector.discover_agenda_urls(
            rss,
            "https://www.bountiful.gov/RSSFeed.aspx?CID=Planning-Commission-6&ModID=65",
        )
        self.assertEqual(
            [
                "https://www.bountiful.gov/AgendaCenter/ViewFile/Agenda/_07212026-863",
                "https://www.bountiful.gov/AgendaCenter/ViewFile/Agenda/_06162026-862",
            ],
            urls,
        )

    def test_june_agenda_keeps_north_canyon_plat_and_site_plan(self):
        text = """
        BOUNTIFUL CITY PLANNING COMMISSION AGENDA TUESDAY, JUNE 16, 2026
        1. Welcome
        2. Meeting Minutes of April 7, 2026 Review Action
        3. Preliminary & Final Plat Approval of the North Canyon Towns PUD Subdivision at 460 West 2600 South Review Recommendation
        4. Architectural & Site Plan for North Canyon Towns at 460 West 2600 South Review Recommendation
        5. Director's Report
        6. Adjourn
        """
        permits = BountifulCollector.parse_agenda_text(text, "https://example.test/june", "2026-06-16")
        self.assertEqual(2, len(permits))
        by_type = {p.permit_type: p for p in permits}
        plat = by_type["Planning Preliminary & Final Plat"]
        self.assertEqual("North Canyon Towns PUD Subdivision", plat.project_name)
        self.assertEqual("460 West 2600 South", plat.address)
        site = by_type["Planning Architectural & Site Plan"]
        self.assertEqual("North Canyon Towns", site.project_name)
        self.assertEqual("460 West 2600 South", site.address)
        for permit in permits:
            classify_permit(permit)
            self.assertFalse(permit.qualifies)
            self.assertEqual("OTHER", permit.classification)

    def test_zone_change_is_retained_and_address_parsed(self):
        text = """
        BOUNTIFUL CITY PLANNING COMMISSION AGENDA TUESDAY, APRIL 7, 2026
        1. Welcome
        2. Meeting Minutes from January 20, 2026
        3. 2523 South 100 West Zone Change from Single-Family Residential (R-4) Subzone to Mixed Use Residential (MXD-R) Review Recommendation
        4. Director's Report
        5. Adjourn
        """
        permits = BountifulCollector.parse_agenda_text(text, "https://example.test/april", "2026-04-07")
        self.assertEqual(1, len(permits))
        permit = permits[0]
        self.assertEqual("Planning Zone Change", permit.permit_type)
        self.assertEqual("2523 South 100 West", permit.address)
        classify_permit(permit)
        self.assertFalse(permit.qualifies)

    def test_architectural_site_plan_projects_are_retained(self):
        text = """
        BOUNTIFUL CITY PLANNING COMMISSION AGENDA TUESDAY, JANUARY 6, 2026
        1. Welcome
        2. Meeting Minutes from December 16, 2025
        3. Final Architectural & Site Plan Review for a Wellness Center at 485 South 100 East Review Recommendation
        4. Final Architectural & Site Plan Review for a Retail Store/Private Fitness Facility at 420 West 500 South Review Recommendation
        5. 2026 Planning Commission Election of Chairperson and Vice-Chair Action
        6. Planning Director's report, update, and miscellaneous items
        7. Adjourn
        """
        permits = BountifulCollector.parse_agenda_text(text, "https://example.test/january", "2026-01-06")
        self.assertEqual(2, len(permits))
        addresses = {p.address for p in permits}
        self.assertEqual({"485 South 100 East", "420 West 500 South"}, addresses)
        self.assertTrue(all(p.permit_type == "Planning Architectural & Site Plan" for p in permits))

    def test_policy_and_low_value_items_are_excluded(self):
        text = """
        BOUNTIFUL CITY PLANNING COMMISSION AGENDA
        1. Welcome
        2. Omnibus Land Use Text Ordinance change to various Code sections
        3. Conditional Use Permit for Home Occupation at 100 North 200 East
        4. Variance Request for an eight-foot wall and gate at 172 East 1500 South
        5. Annual Meeting Schedule Public Notice
        6. Adjourn
        """
        self.assertEqual([], BountifulCollector.parse_agenda_text(text, "https://example.test/noise", "2026-02-03"))

    def test_date_is_derived_from_civicplus_agenda_url(self):
        self.assertEqual(
            "2026-09-15",
            BountifulCollector._date_from_url(
                "https://www.bountiful.gov/AgendaCenter/ViewFile/Agenda/_09152026-968"
            ),
        )


if __name__ == "__main__":
    unittest.main()
