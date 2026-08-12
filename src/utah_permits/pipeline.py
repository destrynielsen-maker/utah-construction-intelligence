from __future__ import annotations

import os
from datetime import datetime, timezone
from pathlib import Path

from .classify import classify_permit
from .collectors.orem import OremCollector
from .collectors.provo import ProvoCollector
from .collectors.summit_county import SummitCountyCollector
from .dashboard import write_public_data
from .feeds import write_all_feeds
from .models import Permit
from .storage import load_permits, save_permits


COLLECTORS = [ProvoCollector(), OremCollector(), SummitCountyCollector()]


def _site_base_url() -> str:
    configured = os.environ.get("SITE_BASE_URL", "").strip()
    if configured:
        return configured.rstrip("/") + "/"
    repo = os.environ.get("GITHUB_REPOSITORY", "")
    if "/" in repo:
        owner, name = repo.split("/", 1)
        return f"https://{owner}.github.io/{name}/"
    return "https://example.invalid/utah-construction-intelligence/"


def run(root: Path) -> dict:
    generated_at = datetime.now(timezone.utc).replace(microsecond=0).isoformat()
    store_path = root / "data" / "permits.json"
    existing = load_permits(store_path)
    source_status: list[dict] = []
    total_collected = 0

    for collector in COLLECTORS:
        try:
            result = collector.collect()
            total_collected += len(result.permits)
            qualified_count = 0
            for permit in result.permits:
                classify_permit(permit)
                if permit.qualifies:
                    qualified_count += 1
                old = existing.get(permit.key)
                permit.first_seen_at = old.first_seen_at if old and old.first_seen_at else generated_at
                permit.last_seen_at = generated_at
                existing[permit.key] = permit
            source_status.append({
                "source": result.source,
                "status": "ok",
                "records_seen": len(result.permits),
                "qualifying_records": qualified_count,
                "source_url": result.source_url,
                "note": result.note,
            })
        except Exception as exc:  # one source must not erase the others
            source_status.append({
                "source": collector.name,
                "status": "error",
                "records_seen": 0,
                "qualifying_records": 0,
                "source_url": getattr(collector, "layer_url", getattr(collector, "pdf_url", getattr(collector, "landing_url", ""))),
                "note": f"{type(exc).__name__}: {exc}",
            })

    permits = list(existing.values())
    # Reclassify old records so scoring/rules can evolve without a data migration.
    for permit in permits:
        classify_permit(permit)

    save_permits(store_path, permits, generated_at)
    public_dir = root / "public"
    write_public_data(public_dir, permits, source_status, generated_at)
    write_all_feeds(public_dir / "feeds", permits, _site_base_url())

    return {
        "generated_at": generated_at,
        "total_collected_this_run": total_collected,
        "total_stored": len(permits),
        "qualifying_stored": sum(p.qualifies for p in permits),
        "sources": source_status,
    }
