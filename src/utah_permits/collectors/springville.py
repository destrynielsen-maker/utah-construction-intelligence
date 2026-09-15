from __future__ import annotations

import hashlib
import re

import requests

from .base import CollectionResult, new_session
from ..models import Permit


class SpringvilleCollector:
    name = "Springville"
    SCOPE_ID = "new-development-gis-v1"
    layer_url = (
        "https://maps.springville.org/server/rest/services/"
        "New_Development_Points/FeatureServer/0"
    )
    PAGE_SIZE = 2000

    def collect(self, session: requests.Session | None = None) -> CollectionResult:
        session = session or new_session()
        features: list[dict] = []
        offset = 0

        while True:
            response = session.get(
                f"{self.layer_url}/query",
                params={
                    "f": "json",
                    "where": "1=1",
                    "outFields": "OBJECTID,Name,Status,Description",
                    "returnGeometry": "false",
                    "orderByFields": "OBJECTID",
                    "resultOffset": offset,
                    "resultRecordCount": self.PAGE_SIZE,
                },
                timeout=45,
            )
            response.raise_for_status()
            payload = response.json()
            if payload.get("error"):
                raise RuntimeError(f"Springville ArcGIS query failed: {payload['error']}")

            page = payload.get("features", [])
            features.extend(page)
            if len(page) < self.PAGE_SIZE and not payload.get("exceededTransferLimit"):
                break
            if not page:
                break
            offset += len(page)

        permits = self.parse_features(features)
        if not permits:
            raise RuntimeError("Springville development layer returned no usable records")

        status_counts: dict[str, int] = {}
        for permit in permits:
            status = str(permit.raw.get("development_status") or "Unknown")
            status_counts[status] = status_counts.get(status, 0) + 1
        status_summary = ", ".join(
            f"{status}: {count}" for status, count in sorted(status_counts.items())
        )

        return CollectionResult(
            self.name,
            permits,
            self.layer_url,
            (
                "Official Springville New Development Points ArcGIS layer; "
                f"{len(permits)} development record(s) ({status_summary}); "
                "source has no per-record date field, so freshness is intentionally unknown; "
                "development-stage intelligence only"
            ),
            scope_id=self.SCOPE_ID,
        )

    @classmethod
    def parse_features(cls, features: list[dict]) -> list[Permit]:
        permits: list[Permit] = []
        seen: set[str] = set()

        for feature in features:
            attrs = feature.get("attributes") or {}
            name = cls._clean(attrs.get("Name"))
            status = cls._clean(attrs.get("Status"))
            description = cls._clean(attrs.get("Description"))
            if not name or not status:
                continue

            digest = hashlib.sha1(
                f"{name}|{status}|{description}".lower().encode("utf-8")
            ).hexdigest()[:12].upper()
            permit_number = f"SPRINGVILLE-DEV-{digest}"
            if permit_number in seen:
                continue
            seen.add(permit_number)

            permits.append(
                Permit(
                    state="UT",
                    jurisdiction=cls.name,
                    permit_number=permit_number,
                    issued_date="",
                    permit_type=status,
                    address="",
                    project_name=name,
                    units=cls._units(description),
                    status=status,
                    source_name="Springville New Development Points",
                    source_url=cls.layer_url,
                    raw={
                        "object_id": attrs.get("OBJECTID"),
                        "development_status": status,
                        "description": description,
                        "lead_stage": "PLANNING",
                        "date_semantics": "undated_source_inventory",
                    },
                )
            )

        return sorted(permits, key=lambda p: (p.project_name or "", p.permit_number))

    @staticmethod
    def _clean(value: object) -> str:
        return re.sub(r"\s+", " ", str(value or "")).strip()

    @staticmethod
    def _units(description: str) -> int | None:
        for pattern in (
            r"\((\d[\d,]*)\s+units?\)",
            r"\b(\d[\d,]*)\s+units?\b",
            r"\b(\d[\d,]*)\s+lots?\b",
        ):
            match = re.search(pattern, description, flags=re.I)
            if match:
                return int(match.group(1).replace(",", ""))
        return None
