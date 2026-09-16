import unittest

from utah_permits.classify import classify_permit
from utah_permits.collectors.woods_cross import WoodsCrossCollector


class WoodsCrossCollectorTests(unittest.TestCase):
    def _notice(self, date_text: str, agenda: str) -> str:
        return f"""
        <html><body>
        <div>Event Start Date &amp; Time {date_text} 06:30 PM</div>
        <div>Description/Agenda WOODS CROSS CITY PLANNING COMMISSION AGENDA {agenda}</div>
        <div>Notice of Special Accommodations (ADA)</div>
        </body></html>
        """

    def test_august_25_keeps_non_home_business_conditional_uses(self):
        html = self._notice(
            "August 25, 2026",
            "1. Pledge Jake Hennessy 2. Meeting Minutes from August 11, 2026 3. Open Session "
            "4. Conditional Use Permit for Wilbur Ellis Company at 1237 West 2285 South Applicant: Michael Koseki Presenter: Curtis Poole - Review - Action "
            "5. Conditional Use Permit for Resilient Roots at 563 West 500 South Applicant: Emerald Baker Presenter: Curtis Poole - Review - Action "
            "6. Director's Report 7. Adjourn",
        )
        permits = WoodsCrossCollector.parse_notice_page(html, "https://example.test/aug25")
        self.assertEqual(2, len(permits))
        names = {p.project_name for p in permits}
        self.assertEqual({"Wilbur Ellis Company", "Resilient Roots"}, names)
        addresses = {p.address for p in permits}
        self.assertEqual({"1237 West 2285 South", "563 West 500 South"}, addresses)
        for permit in permits:
            classify_permit(permit)
            self.assertFalse(permit.qualifies)
            self.assertEqual("OTHER", permit.classification)

    def test_july_site_plan_is_retained_but_adu_is_filtered(self):
        html = self._notice(
            "July 14, 2026",
            "1. Pledge Robin Goodman 2. Meeting Minutes from June 23, 2026 3. Open Session "
            "4. Internal Accessory Dwelling Unit at 1512 West 1200 South Applicant: Joshua Benson Presenter: Curtis Poole - Review - Action "
            "5. Conditional Use Permit for Fancy Tails at 910 South 500 West Applicant: Yuliia Vladimirovna Presenter: Curtis Poole - Review - Action "
            "6. Site Plan Review for Intermountain Sales & Marketing at 965 West 850 South Applicant: Jarred Kennard Presenter: Curtis Poole - Review - Action "
            "7. Director's Report 8. Adjourn",
        )
        permits = WoodsCrossCollector.parse_notice_page(html, "https://example.test/july14")
        self.assertEqual(2, len(permits))
        by_type = {p.permit_type: p for p in permits}
        site = by_type["Planning Site Plan"]
        self.assertEqual("Intermountain Sales & Marketing", site.project_name)
        self.assertEqual("965 West 850 South", site.address)
        self.assertNotIn("1512 West 1200 South", {p.address for p in permits})

    def test_june_light_manufacturing_kept_and_home_occupation_filtered(self):
        html = self._notice(
            "June 9, 2026",
            "1. Pledge Michael Doxey 2. Meeting Minutes from May 26, 2026 3. Open Session "
            "4. Conditional Use Permit for a Home Occupation Nail Tech business at 1402 West 2300 South Applicant: Rachelle Hadley Presenter: Curtis Poole - Review - Action "
            "5. Conditional Use Permit for a Light Manufacturing Business at 2261 South 1560 West Applicant: Alison Christiansen Presenter: Curtis Poole - Review - Action "
            "6. Director's Report 7. Adjourn",
        )
        permits = WoodsCrossCollector.parse_notice_page(html, "https://example.test/june9")
        self.assertEqual(1, len(permits))
        self.assertEqual("Light Manufacturing Business", permits[0].project_name)
        self.assertEqual("2261 South 1560 West", permits[0].address)

    def test_policy_and_adu_agenda_returns_no_project_records(self):
        html = self._notice(
            "September 8, 2026",
            "1. Pledge 2. Meeting Minutes 3. Open Session "
            "4. Internal Accessory Dwelling Unit at 1609 South 580 West Applicant: Alexandre Fonseca - Review - Action "
            "5. Accessory Dwelling Unit Code Text Amendment - Review - Public Hearing - Discussion - Action "
            "6. Discussion: Second Driveway / Hard Surface 7. Director's Report 8. Adjourn",
        )
        self.assertEqual([], WoodsCrossCollector.parse_notice_page(html, "https://example.test/sep8"))

    def test_business_license_policy_hearing_is_filtered(self):
        html = self._notice(
            "September 22, 2026",
            "1. Public Hearing for an amendment to Title 6 Business Regulations of the Woods Cross City Municipal Code for updating and clarifying business licensing 2. Adjourn",
        )
        self.assertEqual([], WoodsCrossCollector.parse_notice_page(html, "https://example.test/sep22"))

    def test_discovery_keeps_meetings_and_hearings_and_skips_cancelled(self):
        html = """
        <a href="/pmn/sitemap/notice/1.html">Planning Commission Meeting</a>
        <a href="/pmn/sitemap/notice/2.html">Public Hearing Notice</a>
        <a href="/pmn/sitemap/notice/3.html">Planning Commission Meeting - CANCELLED</a>
        <a href="/pmn/sitemap/notice/4.html">Annual Meeting Schedule</a>
        """
        urls = WoodsCrossCollector.discover_notice_urls(
            html, "https://www.utah.gov/pmn/sitemap/publicbody/1843.html"
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
