import unittest
from datetime import date
from types import SimpleNamespace

from utah_permits.models import Permit
from utah_permits.pipeline import (
    _freshness,
    _successful_source_status,
    _failed_source_status,
    _volume_health,
)
from utah_permits.collectors.provo import ProvoCollector


class SourceHealthTests(unittest.TestCase):
    def test_provo_uses_live_mapserver(self):
        self.assertEqual(
            ProvoCollector.layer_url,
            "https://gispublicweb.provo.org/arcgis/rest/services/DevServ/CurrentProjects/MapServer/1",
        )
        self.assertTrue(ProvoCollector.query_url.endswith("/MapServer/1/query"))

    def test_freshness_is_source_specific(self):
        status, age, threshold = _freshness("Provo", "2026-08-18", date(2026, 8, 24))
        self.assertEqual((status, age, threshold), ("fresh", 6, 10))
        status, age, threshold = _freshness("Provo", "2026-08-01", date(2026, 8, 24))
        self.assertEqual((status, age, threshold), ("stale", 23, 10))

    def test_volume_drop_detection(self):
        self.assertEqual(_volume_health(900, 1000)[0], "normal")
        self.assertEqual(_volume_health(400, 1000)[0], "warning")
        self.assertEqual(_volume_health(100, 1000)[0], "degraded")

    def test_success_status_marks_stale(self):
        p = Permit(
            state="UT",
            jurisdiction="Orem",
            permit_number="1",
            issued_date="2026-06-01",
            permit_type="New Single Family",
            address="1 Main St",
            source_name="test",
            source_url="https://example.test",
        )
        result = SimpleNamespace(source="Orem", permits=[p], source_url="https://example.test", note="test")
        health = _successful_source_status(
            result,
            qualified_count=1,
            previous=None,
            generated_at="2026-08-24T17:00:00+00:00",
            as_of=date(2026, 8, 24),
        )
        self.assertEqual(health["status"], "stale")
        self.assertEqual(health["technical_status"], "ok")
        self.assertEqual(health["newest_permit_date"], "2026-06-01")

    def test_failed_source_reports_cached_data(self):
        p = Permit(
            state="UT",
            jurisdiction="Provo",
            permit_number="P1",
            issued_date="2026-08-20",
            permit_type="New Residential",
            building_use="SFR",
            address="1 Center St",
            source_name="test",
            source_url="https://example.test",
        )
        existing = {p.key: p}
        previous = {
            "source": "Provo",
            "records_seen": 100,
            "last_success_at": "2026-08-23T17:00:00+00:00",
        }
        health = _failed_source_status(
            ProvoCollector(),
            RuntimeError("test failure"),
            previous,
            existing,
            "2026-08-24T17:00:00+00:00",
            date(2026, 8, 24),
        )
        self.assertEqual(health["status"], "degraded")
        self.assertTrue(health["cached_data_available"])
        self.assertEqual(health["cached_records"], 1)
        self.assertEqual(health["last_success_at"], "2026-08-23T17:00:00+00:00")


if __name__ == "__main__":
    unittest.main()
