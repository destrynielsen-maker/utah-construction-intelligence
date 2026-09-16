from __future__ import annotations

import unittest

from utah_permits.classify import classify_permit
from utah_permits.collectors.riverton import RivertonCollector


class RivertonCollectorTests(unittest.TestCase):
    def test_august_agenda_keeps_development_projects(self) -> None:
        html = """
        <html><body>
        Event Start Date &amp; Time August 27, 2026 06:30 PM
        Description/Agenda PLANNING COMMISSION MEETING AGENDA August 27, 2026
        2. Public Hearings
        2.a 'Quinn Private Lane,' PLZ-26-2038, an application for a conditional use permit for a private lane to provide access for up to three lots, located at 1980 West 13400 South. Applicant - Dallis Quinn
        2.b 'OBO Auto Sales,' PLZ-26-8012 and PLZ-26-2018, an application for a conditional use permit and a commercial site plan for an auto dealer to be located at 2630 and 2610 West 12600 South. Applicants - John Davis and Ryan Harmison
        2.c 'South View Estates,' PLZ-26-1003, an application for approval of a preliminary residential subdivision of up to 5 lots on approximately 3.55-acres located at 13660 South 1300 West. Applicant - Example
        3. Minutes
        Notice of Special Accommodations
        </body></html>
        """
        permits = RivertonCollector.parse_notice_page(html, "https://www.utah.gov/pmn/sitemap/notice/1103905.html")
        self.assertEqual(3, len(permits))
        by_name = {p.project_name: p for p in permits}
        self.assertEqual(3, by_name["Quinn Private Lane"].units)
        self.assertEqual(5, by_name["South View Estates"].units)
        self.assertEqual(3.55, by_name["South View Estates"].raw["acreage"])
        self.assertEqual("13660 South 1300 West", by_name["South View Estates"].address)
        self.assertEqual(["PLZ-26-8012", "PLZ-26-2018"], by_name["OBO Auto Sales"].raw["application_numbers"])
        self.assertEqual("Planning Commercial Site Plan", by_name["OBO Auto Sales"].permit_type)

        for permit in permits:
            classify_permit(permit)
            self.assertFalse(permit.qualifies)
            self.assertEqual("OTHER", permit.classification)
            self.assertEqual(0, permit.score)

    def test_september_filters_policy_and_trivial_change(self) -> None:
        html = """
        <html><body>
        Event Start Date &amp; Time September 10, 2026 06:30 PM
        Description/Agenda PLANNING COMMISSION MEETING AGENDA September 10, 2026
        2. Public Hearings
        2.a 'Jordan Credit Union Amended Site,' PLZ-26-8025, an application to amend a commercial site plan by remodeling the exterior, located at 2522 West 12600 South. Applicant - Reid Wintersteen
        2.b 'Walmart Fuel Station Dumpster Addition,' PLZ-26-8028, an application to amend a commercial site plan located at 13502 South Hamilton View Road by adding a dumpster. Applicant - Jill Yaeger
        2.c 'Land Use Ordinance Amendment,' PLZ-26-5007, Riverton City is proposing changes to Riverton City Code, Title 18 Land Use and Development.
        3. Minutes
        Notice of Special Accommodations
        </body></html>
        """
        permits = RivertonCollector.parse_notice_page(html, "https://www.utah.gov/pmn/sitemap/notice/1107265.html")
        self.assertEqual(1, len(permits))
        permit = permits[0]
        self.assertEqual("Jordan Credit Union Amended Site", permit.project_name)
        self.assertEqual("2522 West 12600 South", permit.address)
        self.assertEqual("2026-09-10", permit.issued_date)
        self.assertEqual("Planning Commercial Site Plan", permit.permit_type)
        self.assertEqual("planning_commission_meeting_date", permit.raw["date_semantics"])

    def test_discovery_keeps_meeting_agendas_and_skips_public_notice_duplicates(self) -> None:
        body = """
        <a href="/pmn/sitemap/notice/1107265.html">Riverton City Planning Commission Meeting</a>
        <a href="/pmn/sitemap/notice/1104769.html">RIVERTON CITY PUBLIC NOTICE</a>
        <a href="/pmn/sitemap/notice/1103905.html">Riverton City Planning Commission Meeting</a>
        <a href="/pmn/sitemap/notice/1103905.html">Riverton City Planning Commission Meeting</a>
        <a href="/pmn/sitemap/notice/1100000.html">Planning Commission Meeting Cancellation</a>
        """
        urls = RivertonCollector.discover_notice_urls(body, RivertonCollector.public_body_url)
        self.assertEqual(
            [
                "https://www.utah.gov/pmn/sitemap/notice/1107265.html",
                "https://www.utah.gov/pmn/sitemap/notice/1103905.html",
            ],
            urls,
        )


if __name__ == "__main__":
    unittest.main()
