from __future__ import annotations

from datetime import datetime, timezone
from email.utils import format_datetime
from html import escape
from pathlib import Path
from xml.etree import ElementTree as ET

from .models import Permit


def _pubdate(iso_date: str) -> str:
    dt = datetime.fromisoformat(iso_date).replace(tzinfo=timezone.utc)
    return format_datetime(dt)


def _money(value: float | None) -> str:
    if value is None:
        return "Not reported"
    return f"${value:,.0f}"


def _title(p: Permit) -> str:
    label = p.classification.replace("_", " ").title()
    descriptor = p.project_name or p.address or f"Permit {p.permit_number}"
    units = f" — {p.units} units" if p.units else ""
    return f"{label}: {descriptor}{units} — {p.jurisdiction}, UT"


def _description(p: Permit) -> str:
    lines = [
        f"<strong>Permit:</strong> {escape(p.permit_number)}",
        f"<strong>Issued:</strong> {escape(p.issued_date)}",
        f"<strong>Type:</strong> {escape(p.permit_type)}",
        f"<strong>Address:</strong> {escape(p.address or 'Not reported')}",
        f"<strong>Valuation:</strong> {_money(p.valuation)}",
        f"<strong>Units:</strong> {p.units if p.units is not None else 'Not reported'}",
        f"<strong>Contractor:</strong> {escape(p.contractor or 'Not reported')}",
        f"<strong>Lead score:</strong> {p.score}",
        f"<strong>New-build confidence:</strong> {escape(p.new_construction_confidence)}",
    ]
    return "<br>".join(lines)


def write_feed(path: Path, permits: list[Permit], title: str, description: str, site_base_url: str) -> None:
    rss = ET.Element("rss", version="2.0")
    channel = ET.SubElement(rss, "channel")
    ET.SubElement(channel, "title").text = title
    ET.SubElement(channel, "link").text = site_base_url
    ET.SubElement(channel, "description").text = description
    ET.SubElement(channel, "language").text = "en-us"
    ET.SubElement(channel, "lastBuildDate").text = format_datetime(datetime.now(timezone.utc))

    for permit in sorted(permits, key=lambda p: (p.issued_date, p.score, p.key), reverse=True)[:500]:
        item = ET.SubElement(channel, "item")
        ET.SubElement(item, "title").text = _title(permit)
        ET.SubElement(item, "link").text = permit.source_url
        guid = ET.SubElement(item, "guid", isPermaLink="false")
        guid.text = permit.key
        ET.SubElement(item, "pubDate").text = _pubdate(permit.issued_date)
        ET.SubElement(item, "description").text = _description(permit)
        ET.SubElement(item, "category").text = permit.classification

    path.parent.mkdir(parents=True, exist_ok=True)
    ET.ElementTree(rss).write(path, encoding="utf-8", xml_declaration=True)


def write_all_feeds(feed_dir: Path, permits: list[Permit], site_base_url: str) -> None:
    qualified = [p for p in permits if p.qualifies]
    feeds = {
        "new-construction.xml": (qualified, "Utah New Construction", "Qualifying new construction permits from supported Utah jurisdictions."),
        "multifamily.xml": ([p for p in qualified if p.classification == "MULTIFAMILY"], "Utah Multifamily Construction", "New multifamily, townhome, duplex, apartment and condominium permits."),
        "single-family.xml": ([p for p in qualified if p.classification == "SINGLE_FAMILY"], "Utah Single-Family Construction", "New single-family building permits."),
        "commercial.xml": ([p for p in qualified if p.classification == "COMMERCIAL"], "Utah Commercial Construction", "Ground-up or structural commercial construction permits."),
        "top-opportunities.xml": ([p for p in qualified if p.score >= 30], "Utah Top Construction Opportunities", "Higher-scoring new construction opportunities based on type, value, units and contractor availability."),
    }
    for filename, (rows, title, description) in feeds.items():
        write_feed(feed_dir / filename, rows, title, description, site_base_url)
