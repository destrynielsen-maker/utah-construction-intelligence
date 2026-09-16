import unittest

from utah_permits.classify import classify_permit
from utah_permits.collectors.north_salt_lake import NorthSaltLakeCollector


def notice_page(date_text: str, agenda: str, title: str = "Meeting Agenda") -> str:
    return f"""
    <html><body>
    <h1>{title}</h1>
    <div>City of North Salt Lake</div>
    <div>Planning Commission</div>
    <div>Event Start Date & Time {date_text} 06:30 PM</div>
    <div>Description/Agenda CITY OF NORTH SALT LAKE PLANNING COMMISSION MEETING NOTICE & AGENDA
    {agenda}
    Planning Commission meetings are open to the public.
    Notice of Special Accommodations</div>
    </body></html>
    """


class NorthSaltLakeCollectorTests(unittest.TestCase):
    def test_discovery_keeps_meetings_and_hearings_and_skips_cancellations(self):
        html = """
        <a href="/pmn/sitemap/notice/1.html">Meeting Agenda</a>
        <a href="/pmn/sitemap/notice/2.html">North Salt Lake Planning Commission</a>
        <a href="/pmn/sitemap/notice/3.html">Notice of Public Hearing</a>
        <a href="/pmn/sitemap/notice/4.html">North Salt Lake Planning Commission - CANCELED</a>
        <a href="/pmn/sitemap/notice/5.html">2026 Meeting Schedule</a>
        """
        urls = NorthSaltLakeCollector.discover_notice_urls(
            html, "https://www.utah.gov/pmn/sitemap/publicbody/453.html"
        )
        self.assertEqual(
            [
                "https://www.utah.gov/pmn/sitemap/notice/1.html",
                "https://www.utah.gov/pmn/sitemap/notice/2.html",
                "https://www.utah.gov/pmn/sitemap/notice/3.html",
            ],
            urls,
        )

    def test_january_general_development_plans_are_retained(self):
        html = notice_page(
            "January 13, 2026",
            """
            AGENDA ITEMS
            1. Welcome and Introduction
            2. Public Comment
            3. Appointment of Chair and Vice Chair for 2026
            4. Consideration of a request to amend the General Development Plan for Clifton Place South PUD, located at 1095 North Redwood Road, 102 Townhomes and 10,500 sq. ft. of commercial, Brighton Homes Utah II, LLC, applicant (administrative)
            5. Consideration of a request to amend the General Development Plan for Village Station, lot 11, located at 445 South Orchard Drive, Brighton Homes Utah II, LLC, applicant (administrative)
            6. Annual Training: Open and Public Meetings Act
            7. Adjourn
            """,
        )
        permits = NorthSaltLakeCollector.parse_notice_page(html, "https://example.test/january")
        self.assertEqual(2, len(permits))
        by_name = {p.project_name: p for p in permits}
        self.assertIn("Clifton Place South PUD", by_name)
        self.assertIn("Village Station, lot 11", by_name)
        self.assertEqual("1095 North Redwood Road", by_name["Clifton Place South PUD"].address)
        self.assertEqual("445 South Orchard Drive", by_name["Village Station, lot 11"].address)
        for permit in permits:
            classify_permit(permit)
            self.assertEqual("OTHER", permit.classification)
            self.assertFalse(permit.qualifies)

    def test_march_preliminary_plats_are_retained(self):
        html = notice_page(
            "March 24, 2026",
            """
            AGENDA ITEMS
            1. Welcome and Introduction
            2. Public Comment
            3. Consideration of Preliminary Plat for The Yard Subdivision at 1155 North Redwood Road, Nick McMurtey, Brighton Homes Utah II, LLC, applicant
            4. Consideration of Preliminary Plat for Clifton Place South PUD Phases 1, 2, & 3 at 1095 North Redwood Road, John Blocker, Brighton Homes Utah II, LLC, applicant
            5. Report on 2026 Legislative Session related to Land Use Code
            6. Adjourn
            """,
        )
        permits = NorthSaltLakeCollector.parse_notice_page(html, "https://example.test/march")
        self.assertEqual(2, len(permits))
        by_name = {p.project_name: p for p in permits}
        self.assertEqual("Planning Preliminary Plat", by_name["The Yard Subdivision"].permit_type)
        self.assertEqual("1155 North Redwood Road", by_name["The Yard Subdivision"].address)
        self.assertEqual("1095 North Redwood Road", by_name["Clifton Place South PUD Phases 1, 2, & 3"].address)

    def test_policy_only_agenda_returns_no_project_records(self):
        html = notice_page(
            "July 14, 2026",
            """
            AGENDA ITEMS
            1. Welcome and Introduction
            2. Public Comment
            3. Work Session - Town Center Urban Design Standards
            4. Report on City Council actions on items recommended by the Planning Commission
            5. Approval of Planning Commission Minutes of May 14, 2026
            6. Adjourn
            """,
        )
        self.assertEqual([], NorthSaltLakeCollector.parse_notice_page(html, "https://example.test/july"))

    def test_code_citation_public_hearing_is_filtered(self):
        html = notice_page(
            "May 12, 2026",
            """
            AGENDA ITEMS
            1. Welcome and Introduction
            2. Public Hearing - consideration of a Code Amendment to update State Code citations in the Land Use Code
            3. Approval of Planning Commission Minutes
            4. Adjourn
            """,
            title="Notice of Public Hearing",
        )
        self.assertEqual([], NorthSaltLakeCollector.parse_notice_page(html, "https://example.test/may"))

    def test_cancelled_notice_is_ignored(self):
        html = notice_page(
            "June 24, 2026",
            "1. North Salt Lake Planning Commission - CANCELED 2. Adjourn",
            title="North Salt Lake Planning Commission - CANCELED",
        )
        self.assertEqual([], NorthSaltLakeCollector.parse_notice_page(html, "https://example.test/cancel"))


if __name__ == "__main__":
    unittest.main()
