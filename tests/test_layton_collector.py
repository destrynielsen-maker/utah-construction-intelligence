import unittest

from utah_permits.classify import classify_permit
from utah_permits.collectors.layton import LaytonCollector


class LaytonCollectorTests(unittest.TestCase):
    def test_poplar_subdivision_keeps_lot_count_and_address(self):
        html = """
        <html><body>
        <div>Event Start Date &amp; Time September 8, 2026 07:00 PM</div>
        <div>Description/Agenda Notice of the Regular Meeting Agenda of the PLANNING COMMISSION OF LAYTON, UTAH.
        PUBLIC MEETING 1. The Poplar Subdivision - PRELIMINARY PLAT The applicants, Keri and John Marsh,
        are requesting preliminary plat approval for The Poplar Subdivision, which includes 32 single-family lots.
        The property is located at approximately 2000 West Gordon Avenue. ADJOURNMENT</div>
        <div>Notice of Special Accommodations</div>
        </body></html>
        """
        permits = LaytonCollector.parse_notice_page(html, "https://example.test/poplar")
        self.assertEqual(1, len(permits))
        permit = permits[0]
        self.assertEqual("The Poplar Subdivision", permit.project_name)
        self.assertEqual(32, permit.units)
        self.assertEqual("2000 West Gordon Avenue", permit.address)
        self.assertEqual("2026-09-08", permit.issued_date)
        classify_permit(permit)
        self.assertFalse(permit.qualifies)
        self.assertEqual("OTHER", permit.classification)

    def test_august_agenda_filters_home_occupation_minor_plat_and_adu(self):
        html = """
        <html><body>
        <div>Event Start Date &amp; Time August 25, 2026 07:00 PM</div>
        <div>Description/Agenda PLANNING COMMISSION OF LAYTON, UTAH PUBLIC MEETING
        1. Kravat Nutrition - CONDITIONAL USE The applicant is requesting a high-impact home occupation at 1954 East Sunset Drive.
        2. Layton Parke Estates Phase 2 Subdivision - 1st Amendment - PLAT AMENDMENT The applicant is transferring 1,350 square feet from Lot 236 to 234. The property is located at approximately 2120 West South Bend Drive.
        PUBLIC HEARING 3. Pheasant Place - REZONE The applicant, representing Pheasant View Assisted Living and Memory Care, is requesting to rezone three areas to facilitate an expansion of Pheasant View Assisted Living and Memory Care. The property is located at approximately 1242 East Pheasant View Drive.
        4. Detached Accessory Dwelling Unit Standards - TEXT AMENDMENT Layton City proposes to amend detached accessory dwelling unit standards. ADJOURNMENT</div>
        <div>Notice of Special Accommodations</div>
        </body></html>
        """
        permits = LaytonCollector.parse_notice_page(html, "https://example.test/august")
        self.assertEqual(1, len(permits))
        permit = permits[0]
        self.assertEqual("Pheasant Place", permit.project_name)
        self.assertEqual("Planning Rezone", permit.permit_type)
        self.assertEqual("1242 East Pheasant View Drive", permit.address)

    def test_july_agenda_retains_midtown_and_filters_minor_amendments(self):
        html = """
        <html><body>
        <div>Event Start Date &amp; Time July 28, 2026 07:00 PM</div>
        <div>Description/Agenda PLANNING COMMISSION OF LAYTON, UTAH PUBLIC MEETING
        1. Jenkins at Three Farms Phase 1 PRUD Subdivision - 1st Amendment - PLAT AMENDMENT The request would transfer approximately 114 square feet to accommodate a neighborhood identification sign. The property is located at approximately 14 South Freedom Farms Drive.
        2. Layton Ridges Subdivision - 2nd Amendment - PLAT AMENDMENT The request is for vacating the Bonneville Shoreline Trail easement and creating a new trail easement. The property is located at approximately 3194 East Layton Ridge Drive.
        3. Layton Midtown - DEVELOPMENT PLAN AMENDMENT The applicant is requesting development plan amendment approval for a 28-unit townhome development in the MU zone. The property is located at 1481 North Hill Field Road. ADJOURNMENT</div>
        <div>Notice of Special Accommodations</div>
        </body></html>
        """
        permits = LaytonCollector.parse_notice_page(html, "https://example.test/july")
        self.assertEqual(1, len(permits))
        permit = permits[0]
        self.assertEqual("Layton Midtown", permit.project_name)
        self.assertEqual(28, permit.units)
        self.assertEqual("Planning Development Plan Amendment", permit.permit_type)

    def test_project_hearing_without_numbered_agenda_is_retained(self):
        html = """
        <html><body>
        <div>Event Start Date &amp; Time September 22, 2026 07:00 PM</div>
        <div>Description/Agenda NOTICE OF PUBLIC HEARING SEPTEMBER 22, 2026 NOTICE IS HEREBY GIVEN that the Layton City Planning Commission will hold a Public Hearing to review a proposal to rezone approximately 1.566 acres of property from CP-2 to M-1. The property is located at approximately 181 and 215 West 2675 North.</div>
        <div>Notice of Special Accommodations</div>
        </body></html>
        """
        permits = LaytonCollector.parse_notice_page(html, "https://example.test/hearing")
        self.assertEqual(1, len(permits))
        permit = permits[0]
        self.assertEqual("Planning Rezone", permit.permit_type)
        self.assertEqual("181 and 215 West 2675 North", permit.address)
        self.assertEqual(1.566, permit.raw["acreage"])
        self.assertEqual("2026-09-22", permit.issued_date)

    def test_discovery_keeps_agendas_and_hearings_but_skips_cancellation(self):
        html = """
        <a href="/pmn/sitemap/notice/1.html">Notice of Public Hearing</a>
        <a href="/pmn/sitemap/notice/2.html">Meeting Agenda</a>
        <a href="/pmn/sitemap/notice/3.html">Canceled Meeting Agenda</a>
        <a href="/pmn/sitemap/noticehistory/4.html">Meeting Agenda Revision</a>
        """
        urls = LaytonCollector.discover_notice_urls(html, "https://www.utah.gov/pmn/sitemap/publicbody/316.html")
        self.assertEqual(
            [
                "https://www.utah.gov/pmn/sitemap/notice/1.html",
                "https://www.utah.gov/pmn/sitemap/notice/2.html",
            ],
            urls,
        )


if __name__ == "__main__":
    unittest.main()
