from __future__ import annotations

import copy
import json
from pathlib import Path

from .classify import classify_permit
from .models import Permit


HISTORY_SCHEMA_VERSION = 1

# Seeded from a read-only Git-history audit on 2026-09-16 comparing the last
# pre-prune published snapshot with the first published 730-day snapshot.
# These are qualifying Provo opportunities only, matching public/permits.json.
HISTORY_SEED = {
    "schema_version": HISTORY_SCHEMA_VERSION,
    "generated_at": None,
    "sources": {
        "Provo": {
            "scope": "qualifying permits archived outside the rolling 730-day active store",
            "archived_qualifying_records": 15482,
            "single_family": 11204,
            "multifamily": 2628,
            "commercial": 1650,
            "other": 0,
            "known_valuation": 4949094085.51,
            "valuation_by_class": {
                "SINGLE_FAMILY": 1279868374.57,
                "MULTIFAMILY": 968399034.09,
                "COMMERCIAL": 2700826676.85,
                "OTHER": 0.0,
            },
            "oldest_issued_date": "1910-01-01",
            "newest_issued_date": "2024-09-12",
            "seed_provenance": {
                "pre_prune_ref": "4e94d3de721688686fafa4d215a043c2d39845bd",
                "first_pruned_ref": "6f4c8fc2ab658446f8f527e4b8aacf2bcb86b178",
                "audit_workflow_run": 35136085937,
                "note": "1910-01-01 is retained as a source-history anomaly; archived totals are not treated as current opportunities.",
            },
        }
    },
}


def seed_history() -> dict:
    return copy.deepcopy(HISTORY_SEED)


def load_history(path: Path) -> dict:
    if not path.exists():
        return seed_history()
    payload = json.loads(path.read_text(encoding="utf-8"))
    if payload.get("schema_version") != HISTORY_SCHEMA_VERSION:
        raise ValueError("Unsupported historical summary schema version")
    if "Provo" not in payload.get("sources", {}):
        raise ValueError("Historical summary is missing Provo source state")
    return payload


def archive_provo_qualifying_history(history: dict, removed: list[Permit], generated_at: str) -> int:
    source = history["sources"]["Provo"]
    previous_newest = source.get("newest_issued_date")
    archived = 0

    for permit in sorted(removed, key=lambda p: (p.issued_date or "", p.key)):
        if permit.jurisdiction != "Provo":
            raise ValueError("Provo history archive received a non-Provo permit")
        classify_permit(permit)
        if not permit.qualifies:
            continue
        # Pruning advances monotonically by issued date. This boundary makes a
        # retry idempotent if the ledger was written but the active store was not.
        if previous_newest and permit.issued_date and permit.issued_date <= previous_newest:
            continue

        classification = permit.classification if permit.classification in {
            "SINGLE_FAMILY", "MULTIFAMILY", "COMMERCIAL"
        } else "OTHER"
        count_key = {
            "SINGLE_FAMILY": "single_family",
            "MULTIFAMILY": "multifamily",
            "COMMERCIAL": "commercial",
            "OTHER": "other",
        }[classification]

        source["archived_qualifying_records"] += 1
        source[count_key] += 1
        value = float(permit.valuation or 0)
        source["known_valuation"] = round(float(source["known_valuation"]) + value, 2)
        source["valuation_by_class"][classification] = round(
            float(source["valuation_by_class"].get(classification, 0)) + value,
            2,
        )
        if permit.issued_date:
            oldest = source.get("oldest_issued_date")
            newest = source.get("newest_issued_date")
            source["oldest_issued_date"] = min(oldest, permit.issued_date) if oldest else permit.issued_date
            source["newest_issued_date"] = max(newest, permit.issued_date) if newest else permit.issued_date
        archived += 1

    history["generated_at"] = generated_at
    return archived


def write_history(history: dict, data_path: Path, public_path: Path, generated_at: str) -> None:
    payload = copy.deepcopy(history)
    payload["generated_at"] = generated_at
    text = json.dumps(payload, indent=2, sort_keys=False)
    data_path.parent.mkdir(parents=True, exist_ok=True)
    public_path.parent.mkdir(parents=True, exist_ok=True)
    data_path.write_text(text, encoding="utf-8")
    public_path.write_text(text, encoding="utf-8")
