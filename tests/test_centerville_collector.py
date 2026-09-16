import unittest

from utah_permits.classify import classify_permit
from utah_permits.collectors.centerville import CentervilleCollector


class CentervilleCollectorTests(unittest.TestCase):
    def test_july_agenda_keeps_fineline_site_plan_and_filters_code_discussion(self):
        html = """
        <html><body>
        <div>Event Start Date &amp; Time July 8, 2026 07:00 PM</div>
        <div>Description/Agenda PLANNING COMMISSION AGENDA A. CALL TO ORDER 1. ROLL CALL 2. PLEDGE OF ALLEGIANCE
        B. BUSINESS ITEMS Business action or discussion items to be considered by the Planning Commission.
        1. Final Site Plan Amendment - Fineline Steel Fabrication - 975 West 50 South - Industrial Development - 975 Fifty LLC - Administrative Decision Consider Final Site Plan Amendment for Fineline Steel Fabrication, located at approximately 975 West 50 South, amending the site plan use, building footprint, and cross-access travel lane connection to the neighboring Steelworks site.
        2. Discussion - First review of draft code concepts for Detached Accessory Dwelling Units (DADU) to be located in Chapter 12 of the Centerville Zoning Code.
        3. Discussion - First review of draft code concepts for Boundary Line Adjustments processing in replacement of Exchange of Title codes.
        C. COMMUNITY DEVELOPMENT DIRECTORS REPORT 1. Community Development Director's Report D. MINUTES 1. Minutes Review and Approval - June 10, 2026 E. ADJOURNMENT</div>
        <div>Notice of Special Accommodations</div>
        </body></html>
        """
        permits = CentervilleCollector.parse_notice_page(html, "https://example.test/july")
        self.assertEqual(1, len(permits))
        permit = permits[0]
        self.assertEqual("Fineline Steel Fabrication", permit.project_name)
        self.assertEqual("975 West 50 South", permit.address)
        self.assertEqual("Planning Final Site Plan Amendment", permit.permit_type)
        self.assertEqual("2026-07-08", permit.issued_date)
        classify_permit(permit)
        self.assertFalse(permit.qualifies)
        self.assertEqual("OTHER", permit.classification)

    def test_april_agenda_keeps_pastures_site_plan_but_filters_landscaping_waiver(self):
        html = """
        <html><body>
        <div>Event Start Date &amp; Time April 22, 2026 07:00 PM</div>
        <div>Description/Agenda A. CALL TO ORDER 1. ROLL CALL B. BUSINESS ITEMS
        1. Waiver of Strict Compliance for Landscaping - Pastures Phase Three - 1265 West 1275 North - Troy and Craig Salmon - Administrative Decision Consider Waiver of Strict Compliance for Landscaping Plan as previously approved with the original Site Plan approval.
        2. Site Plan Amendment - Pastures Phase Three - 1265 West 1275 North - Commercial Development - Troy and Craig Salmon - Administrative Decision Consideration of Final Site Plan Amendment for Pastures Phase Three, located at approximately 1265 West 1275 North, amending the parking configuration, adding new outdoor storage area, and incorporating modifications to the landscaping plan.
        C. COMMUNITY DEVELOPMENT DIRECTORS REPORT 1. Community Development Director's Report D. MINUTES E. ADJOURNMENT</div>
        <div>Notice of Special Accommodations</div>
        </body></html>
        """
        permits = CentervilleCollector.parse_notice_page(html, "https://example.test/april")
        self.assertEqual(1, len(permits))
        permit = permits[0]
        self.assertEqual("Pastures Phase Three", permit.project_name)
        self.assertEqual("1265 West 1275 North", permit.address)
        self.assertEqual("Planning Final Site Plan Amendment", permit.permit_type)

    def test_march_agenda_filters_home_occupation_and_code_only_items(self):
        html = """
        <html><body>
        <div>Event Start Date &amp; Time March 11, 2026 07:00 PM</div>
        <div>Description/Agenda B. BUSINESS ITEMS
        1. Public Hearing - Conditional Use Permit for Home Occupation - 86 South Florentine Lane - Home Occupation Bakery Business - Stacia Liechty - Administrative Decision.
        2. Public Hearing - Zoning Code Amendments - CZC 12.51 Landscaping and Screening and CMC 11.02 Parkstrips and Parkstrip Trees - Legislative Decision regarding water conservation amendments.
        C. COMMUNITY DEVELOPMENT DIRECTORS REPORT 1. Community Development Director's Report D. MINUTES E. ADJOURNMENT</div>
        <div>Notice of Special Accommodations</div>
        </body></html>
        """
        permits = CentervilleCollector.parse_notice_page(html, "https://example.test/march")
        self.assertEqual([], permits)

    def test_standalone_site_plan_hearing_is_retained(self):
        html = """
        <html><body>
        <div>Event Start Date &amp; Time April 22, 2026 07:00 PM</div>
        <div>Description/Agenda CENTERVILLE CITY NOTICE OF PUBLIC HEARING - SITE PLAN AMENDMENT Notice is hereby given that the Centerville City Planning Commission will hold a public hearing regarding a proposed Site Plan Amendment in conjunction with a Landscaping Waiver Of Strict Compliance for the commercial property located at approximately 1265 West 1275 North, known as parcel number 06-003-0056.</div>
        <div>Notice of Special Accommodations</div>
        </body></html>
        """
        permits = CentervilleCollector.parse_notice_page(html, "https://example.test/hearing")
        self.assertEqual(1, len(permits))
        permit = permits[0]
        self.assertEqual("1265 West 1275 North", permit.address)
        self.assertEqual("06-003-0056", permit.apn)
        self.assertEqual("Planning Site Plan Amendment", permit.permit_type)

    def test_cancelled_meeting_is_ignored(self):
        html = """
        <html><body>
        <div>Event Start Date &amp; Time September 9, 2026 07:00 PM</div>
        <div>Description/Agenda PLANNING COMMISSION AGENDA NOTICE IS HEREBY GIVEN THAT THE SEPTEMBER 9TH, 2026, CENTERVILLE PLANNING COMMISSION MEETING HAS BEEN CANCELLED DUE TO HAVING NO REQUESTED AGENDA ACTION ITEMS.</div>
        <div>Notice of Special Accommodations</div>
        </body></html>
        """
        self.assertEqual([], CentervilleCollector.parse_notice_page(html, "https://example.test/cancel"))

    def test_discovery_keeps_meetings_and_hearings_but_skips_cancelled_and_schedule(self):
        html = """
        <a href="/pmn/sitemap/notice/1.html">July 8, 2026 Planning Commission Meeting</a>
        <a href="/pmn/sitemap/notice/2.html">Public Hearing - Site Plan Amendment</a>
        <a href="/pmn/sitemap/notice/3.html">September 9, 2026 Planning Commission Meeting - CANCELLED</a>
        <a href="/pmn/sitemap/notice/4.html">2026 Planning Commission Meeting Schedule</a>
        """
        urls = CentervilleCollector.discover_notice_urls(
            html, "https://www.utah.gov/pmn/sitemap/publicbody/446.html"
        )
        self.assertEqual(
            [
                "https://www.utah.gov/pmn/sitemap/notice/1.html",
                "https://www.utah.gov/pmn/sitemap/notice/2.html",
            ],
            urls,
        )


if __name__ == "__main__":
    unittest.main()
