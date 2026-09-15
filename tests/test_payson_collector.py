from __future__ import annotations

import unittest

from utah_permits.classify import classify_permit
from utah_permits.collectors.payson import PaysonCollector


class PaysonCollectorTests(unittest.TestCase):
    def test_public_body_keeps_project_hearings_and_skips_noise(self) -> None:
        html = """
        <table>
          <tr>
            <td><a href="/pmn/sitemap/notice/1107949.html">Payson City Planning Commission Public Hearing - 3G Zone Change</a></td>
            <td>2026/09/23 06:00 PM</td>
            <td><a href="/files/3g.pdf">PC PH 9-23-2026 3-G Zone Change.pdf</a></td>
          </tr>
          <tr>
            <td><a href="/pmn/sitemap/notice/1107889.html">Payson City Planning Commission Public Hearing</a></td>
            <td>2026/09/23 06:00 PM</td>
            <td><a href="/files/hiatt.pdf">PC PH 9-23-2026 Hiatt Creek B3 Zone Change.pdf</a></td>
          </tr>
          <tr>
            <td><a href="/pmn/sitemap/notice/1100000.html">Payson City Planning Commission Meeting - CANCELLED</a></td>
            <td>2026/09/09 06:00 PM</td>
            <td><a href="/files/cancel.pdf">9-9-2026 PC Cancellation Notice.pdf</a></td>
          </tr>
          <tr>
            <td><a href="/pmn/sitemap/notice/1099999.html">Payson City Planning Commission Meeting</a></td>
            <td>2026/08/12 06:00 PM</td>
            <td><a href="/files/agenda.pdf">8-12-2026 PC Agenda.pdf</a></td>
          </tr>
          <tr>
            <td><a href="/pmn/sitemap/notice/1091000.html">Payson City Planning Commission Public Hearing</a></td>
            <td>2026/06/24 06:00 PM</td>
            <td><a href="/files/mangelson.pdf">PC PH 6-24-2026 Mangelson General Plan Amendment - East Site Comp Plan.pdf</a></td>
          </tr>
        </table>
        """

        permits = PaysonCollector.parse_public_body(
            html,
            "https://www.utah.gov/pmn/sitemap/publicbody/668.html",
        )

        self.assertEqual(3, len(permits))
        self.assertEqual("2026-09-23", permits[0].issued_date)
        names = {p.project_name for p in permits}
        self.assertIn("Payson City Planning Commission Public Hearing - 3G Zone Change", names)
        self.assertIn("Hiatt Creek B3 Zone Change", names)
        self.assertIn("Mangelson General Plan Amendment - East Site Comp Plan", names)

        by_name = {p.project_name: p for p in permits}
        self.assertEqual("Planning Rezone", by_name["Hiatt Creek B3 Zone Change"].permit_type)
        self.assertEqual(
            "Planning General Plan Amendment",
            by_name["Mangelson General Plan Amendment - East Site Comp Plan"].permit_type,
        )

        for permit in permits:
            classify_permit(permit)
            self.assertFalse(permit.qualifies)
            self.assertEqual("OTHER", permit.classification)
            self.assertEqual(0, permit.score)
            self.assertEqual("PLANNING", permit.raw["lead_stage"])

    def test_same_project_keeps_latest_hearing(self) -> None:
        html = """
        <table>
          <tr><td><a href="/pmn/sitemap/notice/2.html">Payson City Planning Commission Public Hearing - 3G Zone Change</a></td><td>2026/09/23 06:00 PM</td></tr>
          <tr><td><a href="/pmn/sitemap/notice/1.html">Payson City Planning Commission Public Hearing - 3G Zone Change</a></td><td>2026/08/01 06:00 PM</td></tr>
        </table>
        """
        permits = PaysonCollector.parse_public_body(html, "https://www.utah.gov/pmn/sitemap/publicbody/668.html")
        self.assertEqual(1, len(permits))
        self.assertEqual("2026-09-23", permits[0].issued_date)


if __name__ == "__main__":
    unittest.main()
