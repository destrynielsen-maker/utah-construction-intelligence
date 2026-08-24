from __future__ import annotations

import json
import os
from datetime import date, datetime, timezone
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

SOURCE_FRESHNESS_DAYS = {
    "Provo": 10,
    "Orem": 40,
    "Summit County": 21,
}

VOLUME_WARNING_DROP = 0.50
VOLUME_DEGRADED_DROP = 0.80
VOLUME_BASELINE_MIN = 20


def _site_base_url() -> str:
    configured = os.environ.get("SITE_BASE_URL", "").strip()
    if configured:
        return configured.rstrip("/") + "/"
    repo = os.environ.get("GITHUB_REPOSITORY", "")
    if "/" in repo:
        owner, name = repo.split("/", 1)
        return f"https://{owner}.github.io/{name}/"
    return "https://example.invalid/utah-construction-intelligence/"


def _load_previous_sources(path: Path) -> dict[str, dict]:
    if not path.exists():
        return {}
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}
    return {
        str(item.get("source")): item
        for item in payload.get("sources", [])
        if item.get("source")
    }


def _valid_dates(permits: list[Permit]) -> list[str]:
    values: list[str] = []
    for permit in permits:
        value = permit.issued_date
        if not value:
            continue
        try:
            date.fromisoformat(value)
        except ValueError:
            continue
        values.append(value)
    return values


def _freshness(source: str, newest_date: str | None, as_of: date) -> tuple[str, int | None, int]:
    threshold = SOURCE_FRESHNESS_DAYS.get(source, 30)
    if not newest_date:
        return "unknown", None, threshold
    age = (as_of - date.fromisoformat(newest_date)).days
    return ("fresh" if age <= threshold else "stale"), age, threshold


def _volume_health(records_seen: int, previous_records_seen: int | None) -> tuple[str, float | None]:
    if not previous_records_seen or previous_records_seen < VOLUME_BASELINE_MIN:
        return "normal", None
    change_pct = ((records_seen - previous_records_seen) / previous_records_seen) * 100
    drop = max(0.0, (previous_records_seen - records_seen) / previous_records_seen)
    if drop >= VOLUME_DEGRADED_DROP:
        return "degraded", change_pct
    if drop >= VOLUME_WARNING_DROP:
        return "warning", change_pct
    return "normal", change_pct


def _successful_source_status(
    result,
    qualified_count: int,
    previous: dict | None,
    generated_at: str,
    as_of: date,
) -> dict:
    records_seen = len(result.permits)
    dates = _valid_dates(result.permits)
    newest = max(dates) if dates else None
    oldest = min(dates) if dates else None
    freshness_status, age_days, threshold = _freshness(result.source, newest, as_of)
    previous_count = None if not previous else previous.get("records_seen")
    volume_status, change_pct = _volume_health(records_seen, previous_count)

    if records_seen == 0:
        status = "no_data"
    elif freshness_status == "stale":
        status = "stale"
    elif volume_status == "degraded":
        status = "degraded"
    elif volume_status == "warning":
        status = "warning"
    else:
        status = "healthy"

    notes = [result.note] if result.note else []
    if freshness_status == "stale":
        notes.append(f"Newest permit is {age_days} days old; threshold is {threshold} days.")
    if volume_status in {"warning", "degraded"} and change_pct is not None:
        notes.append(f"Record volume changed {change_pct:.1f}% from the previous run.")
    if records_seen == 0:
        notes.append("Collector completed but returned zero records.")

    return {
        "source": result.source,
        "status": status,
        "technical_status": "ok",
        "freshness_status": freshness_status,
        "volume_status": volume_status,
        "records_seen": records_seen,
        "qualifying_records": qualified_count,
        "newest_permit_date": newest,
        "oldest_permit_date": oldest,
        "days_since_newest_permit": age_days,
        "freshness_threshold_days": threshold,
        "previous_records_seen": previous_count,
        "record_count_change_pct": None if change_pct is None else round(change_pct, 1),
        "last_attempt_at": generated_at,
        "last_success_at": generated_at,
        "cached_data_available": records_seen > 0,
        "source_url": result.source_url,
        "note": " ".join(notes),
    }


def _failed_source_status(
    collector,
    exc: Exception,
    previous: dict | None,
    existing: dict[str, Permit],
    generated_at: str,
    as_of: date,
) -> dict:
    cached = [p for p in existing.values() if p.jurisdiction == collector.name]
    cached_dates = _valid_dates(cached)
    newest = max(cached_dates) if cached_dates else (previous or {}).get("newest_permit_date")
    oldest = min(cached_dates) if cached_dates else (previous or {}).get("oldest_permit_date")
    freshness_status, age_days, threshold = _freshness(collector.name, newest, as_of)
    last_success = (previous or {}).get("last_success_at")
    cached_available = bool(cached or last_success)
    status = "degraded" if cached_available else "error"

    cached_qualifying = 0
    for permit in cached:
        classify_permit(permit)
        cached_qualifying += int(permit.qualifies)

    note = f"{type(exc).__name__}: {exc}"
    if cached_available:
        note = f"Live collection failed; cached permits retained. {note}"

    return {
        "source": collector.name,
        "status": status,
        "technical_status": "error",
        "freshness_status": freshness_status,
        "volume_status": "unknown",
        "records_seen": 0,
        "qualifying_records": 0,
        "cached_records": len(cached),
        "cached_qualifying_records": cached_qualifying,
        "newest_permit_date": newest,
        "oldest_permit_date": oldest,
        "days_since_newest_permit": age_days,
        "freshness_threshold_days": threshold,
        "previous_records_seen": (previous or {}).get("records_seen"),
        "record_count_change_pct": None,
        "last_attempt_at": generated_at,
        "last_success_at": last_success,
        "cached_data_available": cached_available,
        "source_url": getattr(
            collector,
            "layer_url",
            getattr(collector, "pdf_url", getattr(collector, "landing_url", "")),
        ),
        "note": note,
    }


def run(root: Path) -> dict:
    now = datetime.now(timezone.utc).replace(microsecond=0)
    generated_at = now.isoformat()
    as_of = now.date()
    store_path = root / "data" / "permits.json"
    public_dir = root / "public"
    previous_sources = _load_previous_sources(public_dir / "data" / "sources.json")
    existing = load_permits(store_path)
    source_status: list[dict] = []
    total_collected = 0

    for collector in COLLECTORS:
        previous = previous_sources.get(collector.name)
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
            source_status.append(
                _successful_source_status(result, qualified_count, previous, generated_at, as_of)
            )
        except Exception as exc:
            source_status.append(
                _failed_source_status(collector, exc, previous, existing, generated_at, as_of)
            )

    permits = list(existing.values())
    for permit in permits:
        classify_permit(permit)

    save_permits(store_path, permits, generated_at)
    write_public_data(public_dir, permits, source_status, generated_at)
    write_all_feeds(public_dir / "feeds", permits, _site_base_url())

    return {
        "generated_at": generated_at,
        "total_collected_this_run": total_collected,
        "total_stored": len(permits),
        "qualifying_stored": sum(p.qualifies for p in permits),
        "sources": source_status,
    }
