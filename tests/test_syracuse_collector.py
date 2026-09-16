from __future__ import annotations

import unittest

from utah_permits.classify import classify_permit
from utah_permits.collectors.syracuse import SyracuseCollector


class SyracuseCollectorTests(unittest.TestCase):
    def test_discovery_keeps_planning_commission_and_skips_cancelled(self):
        html = """
        <a href="/AgendaCenter/ViewFile/Agenda/_09012026-791?html=true">Planning Commission Meeting/Public Hearing - Sept 1, 2026</a>
        <a href="/AgendaCenter/ViewFile/Agenda/_09152026-800?html=true">Planning Commission Meeting - Sept 15, 2026 *CANCELED*</a>
        <a href="/AgendaCenter/ViewFile/Agenda/_09082026-799?html=true">Syracuse City Council Business Meeting</a>
        """
        urls = SyracuseCollector.discover_agenda_urls(html, "https://syracuseut.gov/AgendaCenter")
        self.assertEqual(
            ["https://syracuseut.gov/AgendaCenter/ViewFile/Agenda/_09012026-791?html=true"],
            urls,
        )

    def test_detail_page_prefers_public_hearing_pdf(self):
        html = """
        <a href="/AgendaCenter/ViewFile/Item/605?fileID=5154">Public Hearings - 8-18-2026.pdf</a>
        <a href="/AgendaCenter/ViewFile/Item/606?fileID=5155">2026-08-18 Agenda.pdf</a>
        <a href="/AgendaCenter/ViewFile/Item/607?fileID=5156">2026-08-18 Packet.pdf</a>
        """
        self.assertEqual(
            "https://syracuseut.gov/AgendaCenter/ViewFile/Item/605?fileID=5154",
            SyracuseCollector.discover_hearing_pdf_url(html, "https://syracuseut.gov/AgendaCenter/ViewFile/Agenda/_08182026-787?html=true"),
        )

    def test_august_rezone_retained_and_drone_policy_filtered(self):
        text = """
        NOTICE OF PUBLIC HEARING
        The Syracuse Planning Commission will hold a Public Hearing Tuesday, August 18, 2026, at 6 pm to discuss the following matters:
        Public Hearing: Zoning Amendment - Request by RAKE, LLC for a rezone of a property currently zoned A-1 located at app. 2207 W 1700 S on app. 0.249 acre. The proposed zone designation is LC.
        Public Hearing: Ordinance Amendment - Amending Municipal Code to allow for Commercial Drone Operations.
        Connect at https://example.invalid
        """
        rows = SyracuseCollector.parse_hearing_text(text, "https://example.invalid/hearing.pdf", "2026-08-18")
        self.assertEqual(1, len(rows))
        self.assertEqual("2207 W 1700 S", rows[0].address)
        self.assertEqual("RAKE, LLC Rezone", rows[0].project_name)
        self.assertEqual("Planning Zone Change", rows[0].permit_type)

    def test_april_ground_up_projects_retained_revised_site_plan_filtered(self):
        text = """
        NOTICE OF PUBLIC HEARING
        The Syracuse Planning Commission will hold a Public Hearing Tuesday, April 7, 2026, at 6 pm to discuss the following matters:
        Preliminary Plat: Request by Lynsi Neve for approval of the Preliminary Plat for Falcon Landing at approximately 875 S 3000 W. The proposed subdivision comprises approximately 19.7 acres in the R-2 zone.
        Revised Site Plan: Request by Heather Llewelyn for a revision of a Take 5 Oil site plan at approximately 3062 W 1700 S. The proposed site comprises approximately 0.71 acres in the GC zone.
        Site Plan: Request by Logan Johnson for approval of a Dutch Bros commercial site plan located at approximately 2175 W 1700 S. The proposed site comprises approximately 0.991 acres in the LC zone.
        Preliminary Plat: Request by Taylor Anderson for approval of the Preliminary Plat for Lone Tree at approximately 963 S 2000 W. The proposed subdivision comprises approximately 13.395 acres in the R-3 zone.
        Preliminary Plat: Request by Rick Peterson for approval of the Preliminary Plat for The Commons at Glen Eagle at approximately 3400 W 1700 S. The proposed subdivision comprises approximately 5.25 acres in the GC zone.
        Site Plan: Request by Logan Hammer for approval of the Syracuse Arts Academy site plan located at approximately 2965 W 1700 S. The proposed site comprises approximately 4.29 acres in the A-1 zone.
        Connect at https://example.invalid
        """
        rows = SyracuseCollector.parse_hearing_text(text, "https://example.invalid/hearing.pdf", "2026-04-07")
        self.assertEqual(5, len(rows))
        by_address = {row.address: row for row in rows}
        self.assertEqual("Falcon Landing", by_address["875 S 3000 W"].project_name)
        self.assertEqual("Dutch Bros", by_address["2175 W 1700 S"].project_name)
        self.assertEqual("Lone Tree", by_address["963 S 2000 W"].project_name)
        self.assertEqual("The Commons at Glen Eagle", by_address["3400 W 1700 S"].project_name)
        self.assertEqual("Syracuse Arts Academy", by_address["2965 W 1700 S"].project_name)
        self.assertNotIn("3062 W 1700 S", by_address)

    def test_may_commercial_rezone_retained_sign_code_filtered(self):
        text = """
        The Syracuse Planning Commission will hold a Public Hearing Tuesday, May 5, 2026, at 6 pm to discuss the following matters:
        Rezone: Request by Alex Fleischman for a rezone of 5.56 acres from A-1 (Agriculture) to GC (General Commercial) at approx. 2900 W. 1700 S.
        City Code Amendment: Request by Kendall Hawkins for a city code amendment to chapter 10.45 increasing multitenant pole sign height and size allowances.
        Connect at https://example.invalid
        """
        rows = SyracuseCollector.parse_hearing_text(text, "https://example.invalid/hearing.pdf", "2026-05-05")
        self.assertEqual(1, len(rows))
        self.assertEqual("2900 W 1700 S", rows[0].address)
        self.assertEqual("Alex Fleischman Rezone", rows[0].project_name)

    def test_policy_and_ev_only_hearings_return_no_project_rows(self):
        policy = """
        The Syracuse Planning Commission will hold a Public Hearing Tuesday, Sept 1, 2026, to discuss the following matters:
        Ordinance Amendment - Amending City Guidelines for Inorganic Landscaping.
        Connect at https://example.invalid
        """
        ev = """
        The Syracuse Planning Commission will hold a Public Hearing Tuesday, July 21, 2026, to discuss the following matters:
        Text Amendment - Amendment to SCC Chapter 10 creating a process for zoning to revert to its prior designation.
        Site Plan - Converting existing parking into electrical vehicle charging stations within the Walmart site area at 2228 W 1700 S.
        Connect at https://example.invalid
        """
        self.assertEqual([], SyracuseCollector.parse_hearing_text(policy, "https://example.invalid/policy.pdf", "2026-09-01"))
        self.assertEqual([], SyracuseCollector.parse_hearing_text(ev, "https://example.invalid/ev.pdf", "2026-07-21"))

    def test_planning_rows_never_qualify_as_issued_permits(self):
        text = """
        The Syracuse Planning Commission will hold a Public Hearing Tuesday, August 18, 2026, to discuss the following matters:
        Zoning Amendment - Request by RAKE, LLC for a rezone of a property currently zoned A-1 located at app. 2207 W 1700 S on app. 0.249 acre. The proposed zone designation is LC.
        Connect at https://example.invalid
        """
        rows = SyracuseCollector.parse_hearing_text(text, "https://example.invalid/hearing.pdf", "2026-08-18")
        self.assertEqual(1, len(rows))
        classified = classify_permit(rows[0])
        self.assertFalse(classified.qualifies)
        self.assertEqual("OTHER", classified.classification)


if __name__ == "__main__":
    unittest.main()
