from __future__ import annotations

from datetime import datetime, timezone

import requests

from .base import CollectionResult, new_session
from ..models import Permit


class ProvoCollector:
    name = "Provo"
    layer_url = "https://gispublicweb.provo.gov/ArcGIS/rest/services/DevServ/CurrentProjects/FeatureServer/1"
    query_url = layer_url + "/query"

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
        fields = ",".join(self.FIELD.values())
        permits: list[Permit] = []
        offset = 0
        page_size = 2000

        while True:
            params = {
                "where": f"{self.FIELD['issued']} IS NOT NULL",
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
                raise RuntimeError(f"Provo ArcGIS error: {payload['error']}")
            features = payload.get("features", [])
            if not features:
                break

            for feature in features:
                a = feature.get("attributes", {})
                issued = self._epoch_date(a.get(self.FIELD["issued"]))
                number = str(a.get(self.FIELD["number"]) or "").strip()
                if not issued or not number:
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

        return CollectionResult(self.name, permits, self.layer_url, "Official ArcGIS feature layer")

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
