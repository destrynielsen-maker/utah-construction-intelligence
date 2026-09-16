from __future__ import annotations

import unittest

from utah_permits.classify import classify_permit
from utah_permits.collectors.herriman import HerrimanCollector


class HerrimanCollectorTests(unittest.TestCase):
    def test_september_16_subdivision_is_retained_and_nonqualifying(self) -> None:
        html = """
        <html><body>
        Event Start Date &amp; Time September 16, 2026 06:00 PM
        Description/Agenda PLANNING COMMISSION AGENDA Wednesday, September 16, 2026
        1. Commission Business 1.1. Review of City Council Decisions 1.2. Review of Agenda Items
        4. Administrative Items
        4.1. Review and consider a Preliminary Subdivision Plat for one (1) lot located generally at
        5175 W Herriman Main Street in the MU-2 Mixed Use Zone and the Herriman Towne Center Master Development Agreement (MDA).
        (Public Hearing) Applicant: HTC Communities LLC (property owner, authorized agent) Acres: (+/-)6.0 File No: S2026-120
        5. Chair and Commission Comments
        Notice of Special Accommodations
        </body></html>
        """
        permits = HerrimanCollector.parse_notice_page(
            html, "https://www.utah.gov/pmn/sitemap/notice/1107799.html"
        )
        self.assertEqual(1, len(permits))
        permit = permits[0]
        self.assertEqual("HER-PLAN-S2026-120", permit.permit_number)
        self.assertEqual("Planning Subdivision/Plat", permit.permit_type)
        self.assertEqual("2026-09-16", permit.issued_date)
        self.assertEqual("5175 W Herriman Main Street", permit.address)
        self.assertEqual(1, permit.units)
        self.assertEqual(6.0, permit.raw["acreage"])
        self.assertEqual("planning_commission_meeting_date", permit.raw["date_semantics"])

        classify_permit(permit)
        self.assertFalse(permit.qualifies)
        self.assertEqual("OTHER", permit.classification)
        self.assertEqual(0, permit.score)

    def test_september_2_keeps_restaurant_and_filters_sign_and_citywide_code(self) -> None:
        html = """
        <html><body>
        Event Start Date &amp; Time September 2, 2026 06:00 PM
        Description/Agenda PLANNING COMMISSION AGENDA Wednesday, September 02, 2026
        1. Commission Business 1.1. Review of City Council Decisions 1.2. Review of Agenda Items
        4. Administrative Items
        4.1. Review and consider a Conditional Use Permit for a monument sign for Toscano, located at
        12547 Herriman Auto Row, in the C-2 Commercial Zone. Applicant: Jeremy Ford (AFP HGP)
        Acres: (+/-)0.840 acres File No: C2026-116
        4.2. Consideration of a Site Plan for a commercial restaurant at 4948 W 12600 South in the C-2 Commercial Zone
        and Midas Crossing Master Development Agreement. Applicant: Fernando Mendoza (property owner)
        Acres: (+/-)0.184 File No: P2026-121
        5. Legislative Items
        5.1. Review and consider a recommendation to amend Title 10 (Land Development Code) of the Herriman City Code
        to clarify accessory dwelling unit regulations and statutory references. Applicant: Herriman City File No: Z2026-123
        6. Chair and Commission Comments
        Notice of Special Accommodations
        </body></html>
        """
        permits = HerrimanCollector.parse_notice_page(
            html, "https://www.utah.gov/pmn/sitemap/notice/1104661.html"
        )
        self.assertEqual(1, len(permits))
        permit = permits[0]
        self.assertEqual("HER-PLAN-P2026-121", permit.permit_number)
        self.assertEqual("Planning Site Plan", permit.permit_type)
        self.assertEqual("4948 W 12600 South", permit.address)
        self.assertEqual("2026-09-02", permit.issued_date)
        self.assertIn("Commercial Restaurant", permit.project_name)

    def test_discovery_keeps_planning_meetings_and_skips_cancellation(self) -> None:
        body = """
        <a href="/pmn/sitemap/notice/1107799.html">Planning Commision Meeting</a>
        <a href="/pmn/sitemap/notice/1107000.html">Planning Commission Meeting Cancellation</a>
        <a href="/pmn/sitemap/notice/1104661.html">Planning Commision Meeting</a>
        <a href="/pmn/sitemap/notice/1104661.html">Planning Commision Meeting</a>
        <a href="/pmn/sitemap/notice/1106317.html">City Council Regular Session</a>
        """
        urls = HerrimanCollector.discover_notice_urls(body, HerrimanCollector.public_body_url)
        self.assertEqual(
            [
                "https://www.utah.gov/pmn/sitemap/notice/1107799.html",
                "https://www.utah.gov/pmn/sitemap/notice/1104661.html",
            ],
            urls,
        )


if __name__ == "__main__":
    unittest.main()
