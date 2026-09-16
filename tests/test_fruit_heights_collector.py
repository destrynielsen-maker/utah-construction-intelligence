from __future__ import annotations

import unittest

from utah_permits.classify import classify_permit
from utah_permits.collectors.fruit_heights import FruitHeightsCollector


def notice_html(date_text: str, agenda: str) -> str:
    return f"""
    <html><body>
      <h1>Fruit Heights Planning Commission</h1>
      <div>Event Start Date &amp; Time {date_text} 07:00 PM</div>
      <div>Description/Agenda {agenda}</div>
      <div>Notice of Special Accommodations</div>
    </body></html>
    """


class FruitHeightsCollectorTests(unittest.TestCase):
    def test_discovery_keeps_planning_notices_and_skips_cancelled_or_schedule(self):
        html = """
        <a href="/pmn/sitemap/notice/1.html">Planning Commission Meeting 7.28.26</a>
        <a href="/pmn/sitemap/notice/2.html">Public Hearing July 28 RE: Rezone</a>
        <a href="/pmn/sitemap/notice/3.html">Planning Commission Meeting has been canceled</a>
        <a href="/pmn/sitemap/notice/4.html">2026 Meeting Schedule</a>
        """
        urls = FruitHeightsCollector.discover_notice_urls(
            html, "https://www.utah.gov/pmn/sitemap/publicbody/557.html"
        )
        self.assertEqual(
            [
                "https://www.utah.gov/pmn/sitemap/notice/1.html",
                "https://www.utah.gov/pmn/sitemap/notice/2.html",
            ],
            urls,
        )

    def test_july_rezones_and_oakmont_preliminary_plat_are_retained(self):
        agenda = """
        5.1 Rezone approximately 0.701 acres from R-S-12 to R-3 and approximately 0.255 acres from C-2 to R-3. Properties located at 1207 South Main Street
        5.2 Rezone approximately 0.835 acres from C-2 to R-3 Property located at 1112 S Lloyd Road.
        6. Planning Commission Business
        6.1 Rezone approximately 0.701 acres from R-S-12 to R-3 and approximately 0.255 acres from C-2 to R-3. Properties located at 1207 South Main Street
        6.2 Rezone approximately 0.835 acres from C-2 to R-3 Property located at 1112 S Lloyd Road.
        6.3 Preliminary Plat approval for the Oakmont Acres First Amended (1599 N Oakmont Ln)
        6.4 Reviewing MIH strategies
        6.5 General Plan discussion
        10. Closed Meeting
        """
        rows = FruitHeightsCollector.parse_notice_page(
            notice_html("July 28, 2026", agenda),
            "https://www.utah.gov/pmn/sitemap/notice/1097481.html",
        )
        self.assertEqual(3, len(rows))
        by_address = {row.address: row for row in rows}
        self.assertEqual("Planning Zone Change", by_address["1207 South Main Street"].permit_type)
        self.assertEqual("Planning Zone Change", by_address["1112 S Lloyd Road"].permit_type)
        self.assertEqual("Oakmont Acres First Amended", by_address["1599 N Oakmont Ln"].project_name)
        self.assertEqual("Planning Preliminary Plat", by_address["1599 N Oakmont Ln"].permit_type)

    def test_june_eastoaks_preliminary_plat_is_retained(self):
        agenda = """
        5.1 Preliminary Plat approval for the Eastoaks subdivision first amendment (1649 E Eastoaks)
        5.2 Reviewing MIH strategies
        5.3 General Plan discussion
        """
        rows = FruitHeightsCollector.parse_notice_page(
            notice_html("June 30, 2026", agenda),
            "https://www.utah.gov/pmn/sitemap/notice/1091857.html",
        )
        self.assertEqual(1, len(rows))
        self.assertEqual("Eastoaks subdivision first amendment", rows[0].project_name)
        self.assertEqual("1649 E Eastoaks", rows[0].address)
        self.assertEqual("Planning Preliminary Plat", rows[0].permit_type)

    def test_march_rezone_kept_while_wui_and_lot_split_are_filtered(self):
        agenda = """
        5.1 Rezone request on parcels adjacent to 1149 S Mountain Rd and Hidden Springs PKWY
        5.2 Public Hearing RE: Title 10- Chapter 10C - WUI (Wildland Urban Interface)
        5.3 Lot split at 1167 E Goldspur Sub. Orchards at Country Lane
        """
        rows = FruitHeightsCollector.parse_notice_page(
            notice_html("March 25, 2026", agenda),
            "https://www.utah.gov/pmn/sitemap/notice/1067935.html",
        )
        self.assertEqual(1, len(rows))
        self.assertEqual("1149 S Mountain Rd", rows[0].address)
        self.assertEqual("Planning Zone Change", rows[0].permit_type)

    def test_policy_only_agenda_returns_no_project_records(self):
        agenda = """
        5.1 Reviewing MIH strategies
        5.2 General Plan discussion
        5.3 HB48- Wildland Urban Interface Modifications (WUI Code) and map
        """
        rows = FruitHeightsCollector.parse_notice_page(
            notice_html("August 25, 2026", agenda),
            "https://www.utah.gov/pmn/sitemap/notice/1100000.html",
        )
        self.assertEqual([], rows)

    def test_planning_rows_never_qualify_as_issued_permits(self):
        agenda = "5.1 Preliminary Plat approval for the Oakmont Acres First Amended (1599 N Oakmont Ln)"
        rows = FruitHeightsCollector.parse_notice_page(
            notice_html("July 28, 2026", agenda),
            "https://www.utah.gov/pmn/sitemap/notice/1097481.html",
        )
        self.assertEqual(1, len(rows))
        classified = classify_permit(rows[0])
        self.assertFalse(classified.qualifies)
        self.assertEqual("OTHER", classified.classification)


if __name__ == "__main__":
    unittest.main()
