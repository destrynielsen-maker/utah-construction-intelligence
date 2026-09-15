from __future__ import annotations

import unittest

from utah_permits.classify import classify_permit
from utah_permits.collectors.lindon import LindonCollector


class LindonCollectorTests(unittest.TestCase):
    def test_september_agenda_prefers_actual_meeting_date_and_filters_adu_policy(self) -> None:
        html = """
        <html><body>
        Event Start Date &amp; Time September 11, 2026 05:00 PM
        Description/Agenda The Lindon City Planning Commission will hold a regularly scheduled meeting on Tuesday, September 15, 2026, in the Council Room of Lindon City Hall.
        Agenda Invocation: By Invitation Pledge of Allegiance: By Invitation
        1. Call to Order
        2. Approval of minutes - Planning Commission 08/25/2026
        3. Public Comment
        4. Site Plan Approval - Cottonwood Healthcare Corporate Headquarters Brian Swendsen is requesting site plan approval to construct a 46,609-square-foot office building that will serve as the company's corporate headquarters.
        5. Public Hearing - Lindon City Ordinance Amendment The Utah Legislature passed Senate Bill 284 during the 2026 Utah Legislative Session, amending detached accessory dwelling unit requirements.
        6. Community Development Director Report - General City Updates
        Adjourn
        Notice of Special Accommodations
        </body></html>
        """
        permits = LindonCollector.parse_notice_page(html, "https://www.utah.gov/pmn/sitemap/notice/1108315.html")
        self.assertEqual(1, len(permits))
        permit = permits[0]
        self.assertEqual("Cottonwood Healthcare Corporate Headquarters", permit.project_name)
        self.assertEqual("2026-09-15", permit.issued_date)
        self.assertEqual("Planning Site Plan", permit.permit_type)
        self.assertEqual("46,609 sq ft", permit.area)
        self.assertEqual("PLANNING", permit.raw["lead_stage"])
        self.assertEqual("scheduled_planning_meeting_date", permit.raw["date_semantics"])

        classify_permit(permit)
        self.assertFalse(permit.qualifies)
        self.assertEqual("OTHER", permit.classification)
        self.assertEqual(0, permit.score)

    def test_august_agenda_extracts_multiple_project_types(self) -> None:
        html = """
        <html><body>
        Event Start Date &amp; Time August 25, 2026 06:00 PM
        Description/Agenda Agenda
        1. Call to Order
        2. Approval of minutes - Planning Commission 07/14/2026
        3. Public Comment
        4. Conditional Use Permit Lindon Collision, LLC Eric Read requests Conditional Use Permit approval to operate an auto parts manufacturing business at 503 N. Geneva Road.
        5. Site Plan Approval JZ Styles John Clark with Building by John is requesting site plan approval to construct a 31,410-square-foot building to accommodate a salon, retail space, office, warehouse, and fulfillment.
        6. Public Hearing - Lindon City Ordinance Amendment An accessory dwelling unit code amendment.
        Community Development Director Report
        Notice of Special Accommodations
        </body></html>
        """
        permits = LindonCollector.parse_notice_page(html, "https://www.utah.gov/pmn/sitemap/notice/1103749.html")
        self.assertEqual(2, len(permits))
        by_name = {p.project_name: p for p in permits}
        self.assertIn("Lindon Collision Conditional Use Permit", by_name)
        self.assertIn("JZ Styles Commercial Building", by_name)
        self.assertEqual("503 N. Geneva Road", by_name["Lindon Collision Conditional Use Permit"].address)
        self.assertEqual("31,410 sq ft", by_name["JZ Styles Commercial Building"].area)

        for permit in permits:
            classify_permit(permit)
            self.assertFalse(permit.qualifies)
            self.assertEqual(0, permit.score)

    def test_june_agenda_stable_titles_and_discovery(self) -> None:
        html = """
        <html><body>
        Event Start Date &amp; Time June 23, 2026 06:00 PM
        Description/Agenda Agenda 1. Call to Order 2. Approval of minutes 3. Public Comment
        4. Minor Subdivision - Lindon Harbor Industrial Park - Deny Farnworth is proposing a minor subdivision to divide the property located at 1283 W 300 S into two lots.
        5. Minor Subdivision - Blackhurst Manor - Brook Blackhurst is requesting minor subdivision approval to create a one-lot subdivision.
        6. Site Plan - 7 Brew - Toth & Associates, Inc. is requesting site plan approval to construct a fast-food drive-thru business located at 706 N. State Street.
        7. Concept Plan Review - Fortem Building Expansion Lauren Weldon is requesting a concept plan review to receive general feedback for a future addition to the building located at 1855 W. 200 S.
        Adjourn Notice of Special Accommodations
        </body></html>
        """
        permits = LindonCollector.parse_notice_page(html, "https://www.utah.gov/pmn/sitemap/notice/1090761.html")
        self.assertEqual(
            {
                "Lindon Harbor Industrial Park",
                "Blackhurst Manor Subdivision",
                "7 Brew Site Plan",
                "Fortem Building Expansion",
            },
            {p.project_name for p in permits},
        )

        body = """
        <a href="/pmn/sitemap/notice/1108315.html">Planning Commission Meeting</a>
        <a href="/pmn/sitemap/notice/1109999.html">Planning Commission Meeting - CANCELLED</a>
        <a href="/pmn/sitemap/notice/1106485.html">Notice of Public Hearing</a>
        """
        urls = LindonCollector.discover_notice_urls(body, LindonCollector.public_body_url)
        self.assertEqual(["https://www.utah.gov/pmn/sitemap/notice/1108315.html"], urls)


if __name__ == "__main__":
    unittest.main()
