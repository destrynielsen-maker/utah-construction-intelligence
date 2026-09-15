from __future__ import annotations

from datetime import date, datetime, timedelta, timezone

import requests

from .base import CollectionResult, new_session
from ..models import Permit


class ProvoCollector:
    name = "Provo"
    layer_url = "https://gispublicweb.provo.org/arcgis/rest/services/DevServ/CurrentProjects/MapServer/1"
    query_url = layer_url + "/query"
    LOOKBACK_DAYS = 730
    SCOPE_ID = "rolling-730d-v1"

    FIELD = {
        "issued": "xxClient_BP_Applications_View_dateIssued",
        "number": "xxClient_BP_Applications_View_PermitNumber",
        "name": "xxClient_BP_Applications_View_PAName",
        "type": "xxClient_BP_Applications_View_Type",
        "use": "xxClient_BP_Applications_View_BuildingUse",
        "address": "xxClient_BP_Applications_View_streetAddress",
        "units": "xxClient_BP_Applications_View_NumberUnits",
        "valuation": "xxClient_BP_Applications_View_TotalValuation",
        "contractor": "xxClient_BP_Applications_View_ContractorName",
        "status": "xxClient_BP_Applications_View_Status",
    }

    def collect(self, session: requests.Session | None = None) -> CollectionResult:
        session = session or new_session()
        cutoff = date.today() - timedelta(days=self.LOOKBACK_DAYS)
        cutoff_iso = cutoff.isoformat()
        filtered_where = (
            f"{self.FIELD['issued']} >= TIMESTAMP '{cutoff_iso} 00:00:00'"
        )

        permits, used_server_filter = self._collect_pages(session, filtered_where, cutoff_iso)
        if permits is None:
            # Some ArcGIS deployments are picky about date SQL. Fail open to the
            # established query shape, while still enforcing the exact cutoff locally.
            permits, _ = self._collect_pages(
                session,
                f"{self.FIELD['issued']} IS NOT NULL",
                cutoff_iso,
                allow_arcgis_error=False,
            )
            used_server_filter = False

        note = (
            "Official Provo Current Projects MapServer building-permit layer; "
            f"rolling {self.LOOKBACK_DAYS}-day window; "
            + ("server-side date filter active" if used_server_filter else "client-side date fallback active")
        )
        return CollectionResult(
            self.name,
            permits or [],
            self.layer_url,
            note,
            scope_id=self.SCOPE_ID,
        )

    def _collect_pages(
        self,
        session: requests.Session,
        where: str,
        cutoff_iso: str,
        *,
        allow_arcgis_error: bool = True,
    ) -> tuple[list[Permit] | None, bool]:
        fields = ",".join(self.FIELD.values())
        permits: list[Permit] = []
        offset = 0
        page_size = 5000

        while True:
            params = {
                "where": where,
                "outFields": fields,
                "returnGeometry": "false",
                "orderByFields": f"{self.FIELD['issued']} DESC",
                "resultOffset": offset,
                "resultRecordCount": page_size,
                "f": "json",
            }
            response = session.get(self.query_url, params=params, timeout=45)
            response.raise_for_status()
            payload = response.json()
            if "error" in payload:
                if allow_arcgis_error and offset == 0:
                    return None, False
                raise RuntimeError(f"Provo ArcGIS error: {payload['error']}")
            features = payload.get("features", [])
            if not features:
                break

            for feature in features:
                a = feature.get("attributes", {})
                issued = self._epoch_date(a.get(self.FIELD["issued"]))
                number = str(a.get(self.FIELD["number"]) or "").strip()
                if not issued or not number or issued < cutoff_iso:
                    continue
                permits.append(
                    Permit(
                        state="UT",
                        jurisdiction="Provo",
                        permit_number=number,
                        issued_date=issued,
                        permit_type=str(a.get(self.FIELD["type"]) or "").strip(),
                        building_use=str(a.get(self.FIELD["use"]) or "").strip() or None,
                        project_name=str(a.get(self.FIELD["name"]) or "").strip() or None,
                        address=str(a.get(self.FIELD["address"]) or "").strip(),
                        units=self._int_or_none(a.get(self.FIELD["units"])),
                        valuation=self._float_or_none(a.get(self.FIELD["valuation"])),
                        contractor=str(a.get(self.FIELD["contractor"]) or "").strip() or None,
                        status=str(a.get(self.FIELD["status"]) or "").strip() or None,
                        source_name="Provo City Building Permits ArcGIS",
                        source_url=self.layer_url,
                        raw=a,
                    )
                )

            if len(features) < page_size:
                break
            offset += len(features)
            if offset > 100_000:
                raise RuntimeError("Provo pagination safety limit exceeded")

        return permits, True

    @staticmethod
    def _epoch_date(value: object) -> str | None:
        if value in (None, ""):
            return None
        try:
            ms = int(value)
            return datetime.fromtimestamp(ms / 1000, tz=timezone.utc).date().isoformat()
        except (TypeError, ValueError, OSError):
            return None

    @staticmethod
    def _int_or_none(value: object) -> int | None:
        try:
            return int(value) if value not in (None, "") else None
        except (TypeError, ValueError):
            return None

    @staticmethod
    def _float_or_none(value: object) -> float | None:
        try:
            return float(value) if value not in (None, "") else None
        except (TypeError, ValueError):
            return None
