import unittest

from utah_permits.classify import classify_permit
from utah_permits.collectors.kaysville import KaysvilleCollector


class KaysvilleCollectorTests(unittest.TestCase):
    def test_june_hearing_keeps_site_specific_rezone(self):
        html = """
        <html><body>
        <div>Event Start Date &amp; Time June 25, 2026 07:00 PM</div>
        <div>Description/Agenda Kaysville City Planning Commission
        1. Welcome.
        2. Conflict of Interest.
        3. Elect Chair and Vice Chair.
        4. Public Hearing for a rezone request at 820 Mare Circle from A-5 Heavy Agricultural to R-1-6 Single Family Residential for Suzie Hansen.
        5. Approval of Minutes.
        6. Other Matters.
        7. Adjourn.</div>
        <div>Notice of Special Accommodations</div>
        </body></html>
        """
        permits = KaysvilleCollector.parse_notice_page(html, "https://example.test/june")
        self.assertEqual(1, len(permits))
        permit = permits[0]
        self.assertEqual("Planning Rezone", permit.permit_type)
        self.assertEqual("820 Mare Circle", permit.address)
        self.assertEqual("2026-06-25", permit.issued_date)
        classify_permit(permit)
        self.assertFalse(permit.qualifies)
        self.assertEqual("OTHER", permit.classification)

    def test_may_agenda_filters_sign_and_keeps_rezone(self):
        html = """
        <html><body>
        <div>Event Start Date &amp; Time May 28, 2026 07:00 PM</div>
        <div>Description/Agenda Kaysville City Planning Commission
        1. Conditional Use Permit for an electronic message center sign at 368 N Main Street.
        2. Public Hearing to consider an application for a rezone of parcel 08-242-0047 located at 768 W Christopher Circle from R-A to R-1-20.
        3. Approval of Minutes.
        4. Adjourn.</div>
        <div>Notice of Special Accommodations</div>
        </body></html>
        """
        permits = KaysvilleCollector.parse_notice_page(html, "https://example.test/may")
        self.assertEqual(1, len(permits))
        permit = permits[0]
        self.assertEqual("768 W Christopher Circle", permit.address)
        self.assertEqual("08-242-0047", permit.apn)
        self.assertEqual("Planning Rezone", permit.permit_type)

    def test_march_agenda_keeps_multiple_rezones(self):
        html = """
        <html><body>
        <div>Event Start Date &amp; Time March 12, 2026 07:00 PM</div>
        <div>Description/Agenda Kaysville City Planning Commission
        1. Public Hearing for a rezone request for the Angel Street Soccer Complex at 150 South Angel Street from R-A Residential Agriculture to PU Public Use.
        2. Public Hearing for a rezone request for parcel 08-009-0035 located at the southwest corner of Flint Street and Webb Lane from R-1-20 to PU Public Use.
        3. Approval of Minutes.
        4. Adjourn.</div>
        <div>Notice of Special Accommodations</div>
        </body></html>
        """
        permits = KaysvilleCollector.parse_notice_page(html, "https://example.test/march")
        self.assertEqual(2, len(permits))
        named = next(p for p in permits if p.address == "150 South Angel Street")
        self.assertEqual("Angel Street Soccer Complex", named.project_name)
        parcel = next(p for p in permits if p.apn == "08-009-0035")
        self.assertEqual("Planning Rezone", parcel.permit_type)

    def test_september_agenda_filters_home_occupations_and_policy(self):
        html = """
        <html><body>
        <div>Event Start Date &amp; Time September 10, 2026 07:00 PM</div>
        <div>Description/Agenda Kaysville City Planning Commission
        1. Conditional Use Permit Major Home Occupation B at 1795 S 450 E for Miss Megan's Preschool.
        2. Conditional Use Permit Major Home Occupation B for Jeppson Brothers Tree Removal.
        3. Public Hearing for a Text Amendment for Political Signs.
        4. Approval of Minutes.
        5. Adjourn.</div>
        <div>Notice of Special Accommodations</div>
        </body></html>
        """
        permits = KaysvilleCollector.parse_notice_page(html, "https://example.test/september")
        self.assertEqual([], permits)

    def test_discovery_keeps_meetings_and_hearings_but_skips_minutes_and_cancelled(self):
        html = """
        <a href="/pmn/sitemap/notice/1.html">Kaysville City Planning Commission Meeting</a>
        <a href="/pmn/sitemap/notice/2.html">Kaysville City Public Hearing</a>
        <a href="/pmn/sitemap/notice/3.html">Kaysville City Planning Commission Meeting Minutes</a>
        <a href="/pmn/sitemap/notice/4.html">Kaysville City Planning Commission Meeting - Cancelled</a>
        """
        urls = KaysvilleCollector.discover_notice_urls(
            html, "https://www.utah.gov/pmn/sitemap/publicbody/1546.html"
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
