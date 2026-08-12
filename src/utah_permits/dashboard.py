from __future__ import annotations

import json
from collections import defaultdict
from datetime import date, timedelta
from pathlib import Path

from .models import Permit


def write_public_data(public_dir: Path, permits: list[Permit], source_status: list[dict], generated_at: str) -> None:
    qualified = [p for p in permits if p.qualifies]
    data_dir = public_dir / "data"
    data_dir.mkdir(parents=True, exist_ok=True)
    (data_dir / "permits.json").write_text(
        json.dumps({"generated_at": generated_at, "permits": [p.to_dict() for p in qualified]}, indent=2),
        encoding="utf-8",
    )
    (data_dir / "sources.json").write_text(
        json.dumps({"generated_at": generated_at, "sources": source_status}, indent=2),
        encoding="utf-8",
    )
    (data_dir / "builders.json").write_text(
        json.dumps({"generated_at": generated_at, "builders": builder_rollups(qualified)}, indent=2),
        encoding="utf-8",
    )


def builder_rollups(permits: list[Permit]) -> list[dict]:
    cutoff = (date.today() - timedelta(days=90)).isoformat()
    groups: dict[str, list[Permit]] = defaultdict(list)
    for permit in permits:
        if permit.contractor and permit.issued_date >= cutoff:
            groups[permit.contractor.strip()].append(permit)
    rows = []
    for contractor, items in groups.items():
        rows.append({
            "contractor": contractor,
            "permits_90d": len(items),
            "single_family": sum(p.classification == "SINGLE_FAMILY" for p in items),
            "multifamily": sum(p.classification == "MULTIFAMILY" for p in items),
            "commercial": sum(p.classification == "COMMERCIAL" for p in items),
            "combined_valuation": sum(p.valuation or 0 for p in items),
            "jurisdictions": sorted({p.jurisdiction for p in items}),
            "top_score": max((p.score for p in items), default=0),
        })
    return sorted(rows, key=lambda r: (r["permits_90d"], r["combined_valuation"]), reverse=True)
