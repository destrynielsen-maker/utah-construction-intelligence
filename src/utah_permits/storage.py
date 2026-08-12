from __future__ import annotations

import json
from pathlib import Path
from typing import Iterable

from .models import Permit


def load_permits(path: Path) -> dict[str, Permit]:
    if not path.exists():
        return {}
    payload = json.loads(path.read_text(encoding="utf-8"))
    records = payload.get("permits", payload if isinstance(payload, list) else [])
    permits = [Permit.from_dict(row) for row in records]
    return {permit.key: permit for permit in permits}


def save_permits(path: Path, permits: Iterable[Permit], generated_at: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    rows = sorted(
        (p.to_dict() for p in permits),
        key=lambda row: (row.get("issued_date") or "", row.get("score") or 0, row.get("key") or ""),
        reverse=True,
    )
    payload = {"generated_at": generated_at, "permits": rows}
    path.write_text(json.dumps(payload, indent=2, sort_keys=False), encoding="utf-8")
