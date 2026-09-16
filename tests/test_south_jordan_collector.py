from __future__ import annotations

import unittest

from utah_permits.classify import classify_permit
from utah_permits.collectors.south_jordan import SouthJordanCollector


class SouthJordanCollectorTests(unittest.TestCase):
    def test_september_hearing_keeps_project_and_excludes_policy_item(self) -> None:
        html = """
        <html><body>
        Event Start Date &amp; Time September 8, 2026 06:30 PM
        Description/Agenda NOTICE OF PUBLIC HEARING Notice is hereby given that the South Jordan City Planning Commission
        will hold a meeting for the purpose of receiving public input on and reviewing each of the following:
        - PLCUP202600160 - Master Auto Tech, Conditional Use Permit, 11048 Redwood Road, Applicant (David George)
        - PLZTA202600164 - ORDINANCE NO. 2026 - 24 Legislative Updates to ADU and Accessory Building Standards in Chapters 17.08 and 17.30 of City Code, City of South Jordan (Applicant)
        The meeting may also be joined virtually via Zoom.us phone and video conferencing.
        Notice of Special Accommodations
        </body></html>
        """
        permits = SouthJordanCollector.parse_notice_page(html, "https://www.utah.gov/pmn/sitemap/notice/1104623.html")
        self.assertEqual(1, len(permits))
        permit = permits[0]
        self.assertEqual("SOJ-PLAN-PLCUP202600160", permit.permit_number)
        self.assertEqual("Master Auto Tech", permit.project_name)
        self.assertEqual("11048 Redwood Road", permit.address)
        self.assertEqual("2026-09-08", permit.issued_date)
        self.assertEqual("Planning Conditional Use", permit.permit_type)
        self.assertEqual("scheduled_public_hearing_date", permit.raw["date_semantics"])

        classify_permit(permit)
        self.assertFalse(permit.qualifies)
        self.assertEqual("OTHER", permit.classification)
        self.assertEqual(0, permit.score)

    def test_july_hearing_keeps_site_plans_and_rezone_but_excludes_adu(self) -> None:
        html = """
        <html><body>
        Event Start Date &amp; Time July 28, 2026 06:30 PM
        Description/Agenda NOTICE OF PUBLIC HEARING reviewing each of the following:
        - PLMPA202600108 - Sri Ganesha Hindu Temple, Major Site Plan Amendment, 1131 W. 10290 S., Aditya Vinadhara (Applicant)
        - PLSPR202600118 - Beauty Barn, Site Plan, 10956 S. Jordan Gateway, Nichols Naylor Architects (applicant)
        - PLSPR202600076 - 7 Brew Coffee, Site Plan, 3634 W 11400 S, Janis Wren (applicant)
        - PLCUP202600093 - Peck Garage & ADU, Conditional Use Permit, 11756 S Gold Dust Drive, Sadi Peck (applicant)
        - PLZBA202600119 - Fitzgerald & Wagstaff Rezone, Zoning Amendment, 3250 W 11400 S, Mark Wagstaff (applicant)
        The meeting may also be joined virtually via Zoom.us phone and video conferencing.
        Notice of Special Accommodations
        </body></html>
        """
        permits = SouthJordanCollector.parse_notice_page(html, "https://www.utah.gov/pmn/sitemap/notice/1096083.html")
        self.assertEqual(4, len(permits))
        by_name = {p.project_name: p for p in permits}
        self.assertIn("Sri Ganesha Hindu Temple", by_name)
        self.assertIn("Beauty Barn", by_name)
        self.assertIn("7 Brew Coffee", by_name)
        self.assertIn("Fitzgerald & Wagstaff Rezone", by_name)
        self.assertNotIn("Peck Garage & ADU", by_name)
        self.assertEqual("10956 S. Jordan Gateway", by_name["Beauty Barn"].address)
        self.assertEqual("Planning Rezone", by_name["Fitzgerald & Wagstaff Rezone"].permit_type)

    def test_discovery_keeps_public_hearings_and_skips_other_notice_types(self) -> None:
        body = """
        <a href="/pmn/sitemap/notice/1106493.html">Planning Commission Meeting</a>
        <a href="/pmn/sitemap/notice/1104623.html">Notice of Public Hearing</a>
        <a href="/pmn/sitemap/notice/1103000.html">Notice of Meeting Cancellation</a>
        <a href="/pmn/sitemap/notice/1096083.html">Notice of Public Hearing</a>
        <a href="/pmn/sitemap/notice/1096083.html">Notice of Public Hearing</a>
        """
        urls = SouthJordanCollector.discover_notice_urls(body, SouthJordanCollector.public_body_url)
        self.assertEqual(
            [
                "https://www.utah.gov/pmn/sitemap/notice/1104623.html",
                "https://www.utah.gov/pmn/sitemap/notice/1096083.html",
            ],
            urls,
        )


if __name__ == "__main__":
    unittest.main()
