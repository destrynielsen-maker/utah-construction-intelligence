from pathlib import Path
from tempfile import TemporaryDirectory
import unittest

from utah_permits.history import (
    archive_provo_qualifying_history,
    load_history,
    seed_history,
    write_history,
)
from utah_permits.models import Permit


class ProvoHistoryTests(unittest.TestCase):
    def permit(self, number: str, issued: str, use: str, valuation: float, permit_type: str = "New Construction") -> Permit:
        return Permit(
            state="UT",
            jurisdiction="Provo",
            permit_number=number,
            issued_date=issued,
            permit_type=permit_type,
            address="1 Main St",
            source_name="test",
            source_url="https://example.test",
            building_use=use,
            valuation=valuation,
        )

    def test_seed_matches_verified_prune_delta(self):
        source = seed_history()["sources"]["Provo"]
        self.assertEqual(source["archived_qualifying_records"], 15482)
        self.assertEqual(source["single_family"], 11204)
        self.assertEqual(source["multifamily"], 2628)
        self.assertEqual(source["commercial"], 1650)
        self.assertAlmostEqual(source["known_valuation"], 4949094085.51, places=2)
        self.assertEqual(source["newest_issued_date"], "2024-09-12")

    def test_archive_adds_only_newer_qualifying_provo_rows(self):
        history = seed_history()
        removed = [
            self.permit("A", "2024-09-17", "SFR", 500000),
            self.permit("B", "2024-09-18", "COM", 2000000),
            self.permit("C", "2024-09-11", "SFR", 100000),
            self.permit("D", "2024-09-19", "SFR", 75000, permit_type="Remodel"),
        ]
        archived = archive_provo_qualifying_history(history, removed, "2026-09-16T18:00:00+00:00")
        source = history["sources"]["Provo"]
        self.assertEqual(archived, 2)
        self.assertEqual(source["archived_qualifying_records"], 15484)
        self.assertEqual(source["single_family"], 11205)
        self.assertEqual(source["commercial"], 1651)
        self.assertAlmostEqual(source["known_valuation"], 4951594085.51, places=2)
        self.assertEqual(source["newest_issued_date"], "2024-09-18")

    def test_archive_retry_is_idempotent_by_date_boundary(self):
        history = seed_history()
        removed = [self.permit("A", "2024-09-17", "SFR", 500000)]
        self.assertEqual(archive_provo_qualifying_history(history, removed, "run-1"), 1)
        self.assertEqual(archive_provo_qualifying_history(history, removed, "run-2"), 0)
        self.assertEqual(history["sources"]["Provo"]["archived_qualifying_records"], 15483)

    def test_write_and_load_round_trip(self):
        with TemporaryDirectory() as tmp:
            root = Path(tmp)
            history = seed_history()
            write_history(history, root / "data" / "history.json", root / "public" / "data" / "history.json", "stamp")
            loaded = load_history(root / "data" / "history.json")
            self.assertEqual(loaded["generated_at"], "stamp")
            self.assertEqual(loaded["sources"]["Provo"]["archived_qualifying_records"], 15482)
            self.assertTrue((root / "public" / "data" / "history.json").exists())

    def test_archive_rejects_non_provo_rows(self):
        history = seed_history()
        permit = self.permit("X", "2024-09-17", "SFR", 1)
        permit.jurisdiction = "Orem"
        with self.assertRaises(ValueError):
            archive_provo_qualifying_history(history, [permit], "stamp")


if __name__ == "__main__":
    unittest.main()
