from __future__ import annotations

import unittest
from datetime import date, datetime, timedelta, timezone

from utah_permits.collectors.provo import ProvoCollector


class FakeResponse:
    def __init__(self, payload):
        self._payload = payload

    def raise_for_status(self):
        return None

    def json(self):
        return self._payload


class FakeSession:
    def __init__(self, payloads):
        self.payloads = list(payloads)
        self.calls = []

    def get(self, url, params=None, timeout=None):
        self.calls.append({"url": url, "params": dict(params or {}), "timeout": timeout})
        return FakeResponse(self.payloads.pop(0))


def epoch_ms(value: date) -> int:
    dt = datetime(value.year, value.month, value.day, tzinfo=timezone.utc)
    return int(dt.timestamp() * 1000)


def attrs(collector: ProvoCollector, *, issued: date, number: str):
    f = collector.FIELD
    return {
        f["issued"]: epoch_ms(issued),
        f["number"]: number,
        f["name"]: "Test Residence",
        f["type"]: "New Single Family Dwelling",
        f["use"]: "SFR",
        f["address"]: "123 TEST ST",
        f["units"]: 1,
        f["valuation"]: 650000,
        f["contractor"]: "TEST BUILDER",
        f["status"]: "Issued",
    }


class ProvoCollectorTests(unittest.TestCase):
    def test_rolling_window_filters_old_records_and_uses_server_date_query(self):
        collector = ProvoCollector()
        today = date.today()
        recent = today - timedelta(days=30)
        old = today - timedelta(days=collector.LOOKBACK_DAYS + 30)
        session = FakeSession([
            {"features": [
                {"attributes": attrs(collector, issued=recent, number="RECENT-1")},
                {"attributes": attrs(collector, issued=old, number="OLD-1")},
            ]}
        ])

        result = collector.collect(session=session)

        self.assertEqual([p.permit_number for p in result.permits], ["RECENT-1"])
        self.assertEqual(result.scope_id, collector.SCOPE_ID)
        self.assertIn("rolling 730-day window", result.note)
        self.assertIn("TIMESTAMP", session.calls[0]["params"]["where"])
        self.assertEqual(session.calls[0]["params"]["resultRecordCount"], 5000)

    def test_arcgis_date_sql_error_falls_back_to_unbounded_query_but_keeps_cutoff(self):
        collector = ProvoCollector()
        recent = date.today() - timedelta(days=14)
        session = FakeSession([
            {"error": {"code": 400, "message": "Invalid where clause"}},
            {"features": [{"attributes": attrs(collector, issued=recent, number="RECENT-2")}]},
        ])

        result = collector.collect(session=session)

        self.assertEqual([p.permit_number for p in result.permits], ["RECENT-2"])
        self.assertEqual(len(session.calls), 2)
        self.assertIn("IS NOT NULL", session.calls[1]["params"]["where"])
        self.assertIn("client-side date fallback active", result.note)


if __name__ == "__main__":
    unittest.main()
