from __future__ import annotations

import unittest

from utah_permits.classify import classify_permit
from utah_permits.collectors.clinton import ClintonCollector


def notice_html(date_text: str, agenda: str) -> str:
    return f"""
    <html><body>
      <h1>Clinton Planning Commission</h1>
      <div>Event Start Date &amp; Time {date_text} 06:00 PM</div>
      <div>Description/Agenda {agenda}</div>
      <div>Notice of Special Accommodations</div>
    </body></html>
    """


class ClintonCollectorTests(unittest.TestCase):
    def test_discovery_keeps_agendas_and_hearings_and_skips_cancelled(self):
        html = """
        <a href="/pmn/sitemap/notice/1.html">Planning Commission / Public Hearing</a>
        <a href="/pmn/sitemap/notice/2.html">Notice of Public Hearing</a>
        <a href="/pmn/sitemap/notice/3.html">Planning Commission Meeting - Cancelled</a>
        <a href="/pmn/sitemap/notice/4.html">2026 Meeting Schedule</a>
        """
        urls = ClintonCollector.discover_notice_urls(
            html, "https://www.utah.gov/pmn/sitemap/publicbody/301.html"
        )
        self.assertEqual(
            [
                "https://www.utah.gov/pmn/sitemap/notice/1.html",
                "https://www.utah.gov/pmn/sitemap/notice/2.html",
            ],
            urls,
        )

    def test_august_agenda_keeps_vk_site_plan_and_filters_policy(self):
        agenda = """
        1. Public Hearing & Action- on a request by Shane King with VK Electric for Site Plan Review of a multi-tenant retail building on 5.53 acres located at 2057 West 1800 North (Parcel No. 14-021-0133).
        2. Public Hearing & Action - on amendments to the Zoning Ordinance text Section 28-3-27 - Accessory Dwelling Unit Standards.
        3. Action Item - West Clinton annexation area proposed zoning map and annexation agreement.
        Other Business 1. Approval of June 18, 2026 Meeting Minutes
        """
        rows = ClintonCollector.parse_notice_page(
            notice_html("August 6, 2026", agenda),
            "https://www.utah.gov/pmn/sitemap/notice/1098855.html",
        )
        self.assertEqual(1, len(rows))
        self.assertEqual("VK Electric Multi-Tenant Retail Building", rows[0].project_name)
        self.assertEqual("2057 West 1800 North", rows[0].address)
        self.assertEqual("Planning Site Plan", rows[0].permit_type)

    def test_standalone_vk_hearing_has_same_stable_id_as_agenda(self):
        agenda_item = (
            "1. Public Hearing & Action- on a request by Shane King with VK Electric for Site Plan Review "
            "of a multi-tenant retail building on 5.53 acres located at 2057 West 1800 North."
        )
        hearing = (
            "NOTICE OF PUBLIC HEARING VK Electric Multi-Tenant Retail Building SITE PLAN REVIEW NOTICE IS HEREBY GIVEN "
            "that a public hearing is scheduled. Review and action on a request by Shane King with VK Electric for "
            "site plan review for a proposed multi-tenant commercial building and site, located at 2057 West 1800 North."
        )
        agenda_rows = ClintonCollector.parse_notice_page(
            notice_html("August 6, 2026", agenda_item),
            "https://www.utah.gov/pmn/sitemap/notice/1098855.html",
        )
        hearing_rows = ClintonCollector.parse_notice_page(
            notice_html("August 6, 2026", hearing),
            "https://www.utah.gov/pmn/sitemap/notice/1097317.html",
        )
        self.assertEqual(1, len(agenda_rows))
        self.assertEqual(1, len(hearing_rows))
        self.assertEqual(agenda_rows[0].permit_number, hearing_rows[0].permit_number)

    def test_backyard_butcher_permanent_business_cup_is_retained(self):
        agenda = """
        1. Backyard Butcher Conditional Use Permit
        2. Land Use Training - Legislative Update
        Other Business 1. Approval of March 5, 2026 Meeting Minutes
        """
        rows = ClintonCollector.parse_notice_page(
            notice_html("April 2, 2026", agenda),
            "https://www.utah.gov/pmn/sitemap/notice/1069207.html",
        )
        self.assertEqual(1, len(rows))
        self.assertEqual("Backyard Butcher", rows[0].project_name)
        self.assertEqual("Planning Conditional Use", rows[0].permit_type)

    def test_temporary_fireworks_cup_is_filtered(self):
        agenda = (
            "1. Public Hearing - Review and action on a Conditional Use Permit request by Dragon Dynamite Fireworks "
            "for a fireworks sales tent at 1896 North 2000 West."
        )
        rows = ClintonCollector.parse_notice_page(
            notice_html("June 18, 2026", agenda),
            "https://www.utah.gov/pmn/sitemap/notice/1088733.html",
        )
        self.assertEqual([], rows)

    def test_planning_rows_never_qualify_as_issued_permits(self):
        agenda = (
            "1. Public Hearing & Action- on a request by Shane King with VK Electric for Site Plan Review "
            "of a multi-tenant retail building on 5.53 acres located at 2057 West 1800 North."
        )
        rows = ClintonCollector.parse_notice_page(
            notice_html("August 6, 2026", agenda),
            "https://www.utah.gov/pmn/sitemap/notice/1098855.html",
        )
        self.assertEqual(1, len(rows))
        classified = classify_permit(rows[0])
        self.assertFalse(classified.qualifies)
        self.assertEqual("OTHER", classified.classification)


if __name__ == "__main__":
    unittest.main()
