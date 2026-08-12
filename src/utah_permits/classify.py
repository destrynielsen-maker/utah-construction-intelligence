from __future__ import annotations

import re

from .models import Permit


MULTIFAMILY_CODES = {"MFR", "COT", "TFR"}
COMMERCIAL_CODES = {"COM", "IND", "INS", "MED"}
SINGLE_FAMILY_CODES = {"SFR"}


def _norm(value: str | None) -> str:
    return re.sub(r"\s+", " ", (value or "").strip()).lower()


def _source_specific_classification(p: Permit) -> tuple[str, bool, str] | None:
    source = _norm(p.jurisdiction)
    permit_type = _norm(p.permit_type)
    building_use = (p.building_use or "").strip().upper()

    if source == "orem":
        if permit_type == "single family dwelling":
            return "SINGLE_FAMILY", True, "HIGH"
        if permit_type == "town homes":
            return "MULTIFAMILY", True, "HIGH"
        if permit_type in {"new commercial bldg", "new commercial building"}:
            return "COMMERCIAL", True, "HIGH"
        return "OTHER", False, "HIGH"

    if source == "summit county":
        if "multi-family" in permit_type or "apartments or condominiums" in permit_type:
            return "MULTIFAMILY", True, "HIGH"
        if "new single family attached" in permit_type or "duplex" in permit_type:
            return "MULTIFAMILY", True, "HIGH"
        if "single family detached (new construction)" in permit_type or "new single family detached" in permit_type:
            return "SINGLE_FAMILY", True, "HIGH"
        if permit_type.startswith("commercial:"):
            structural_signals = (
                "shell",
                "parking garages",
                "places of religious worship",
                "motor fuel-dispensing facilities",
                "agricultural buildings, not accessory",
            )
            if any(signal in permit_type for signal in structural_signals):
                return "COMMERCIAL", True, "MEDIUM"
            return "OTHER", False, "MEDIUM"
        return "OTHER", False, "HIGH"

    if source == "provo":
        negative = (
            "remodel", "alteration", "addition", "tenant", "repair", "roof", "solar",
            "siding", "electrical", "mechanical", "plumbing", "sign", "demolition",
            "accessory", "retaining", "pool", "deck", "racking", "cell tower",
            "generator", "utility", "service upgrade", "interior finish",
        )
        explicit_new = any(
            phrase in permit_type
            for phrase in (
                "new construction", "new commercial", "new building", "new residential",
                "single family dwelling", "single family detached", "town home", "townhome",
                "duplex", "multi-family", "multifamily", "apartment", "condominium", "shell",
            )
        )
        if not explicit_new and any(term in permit_type for term in negative):
            return "OTHER", False, "HIGH"
        if building_use in MULTIFAMILY_CODES:
            return "MULTIFAMILY", explicit_new, "HIGH" if explicit_new else "LOW"
        if building_use in SINGLE_FAMILY_CODES:
            return "SINGLE_FAMILY", explicit_new, "HIGH" if explicit_new else "LOW"
        if building_use in COMMERCIAL_CODES:
            commercial_new = explicit_new or "shell" in permit_type
            return "COMMERCIAL", commercial_new, "HIGH" if commercial_new else "LOW"
        return "OTHER", False, "LOW"

    return None


def classify_permit(p: Permit) -> Permit:
    specific = _source_specific_classification(p)
    if specific:
        p.classification, p.qualifies, p.new_construction_confidence = specific
    else:
        text = _norm(" ".join(filter(None, [p.permit_type, p.building_use, p.project_name])))
        if any(x in text for x in ("multi-family", "multifamily", "apartment", "condominium", "townhome", "town home", "duplex")):
            p.classification = "MULTIFAMILY"
        elif any(x in text for x in ("single family", "single-family")):
            p.classification = "SINGLE_FAMILY"
        elif "commercial" in text:
            p.classification = "COMMERCIAL"
        else:
            p.classification = "OTHER"
        p.qualifies = p.classification != "OTHER" and any(x in text for x in ("new", "shell"))
        p.new_construction_confidence = "MEDIUM" if p.qualifies else "LOW"

    p.score = score_permit(p)
    return p


def score_permit(p: Permit) -> int:
    base = {
        "MULTIFAMILY": 40,
        "COMMERCIAL": 30,
        "SINGLE_FAMILY": 15,
    }.get(p.classification, 0)

    if not p.qualifies:
        return 0

    score = base
    value = p.valuation or 0
    if value >= 25_000_000:
        score += 20
    elif value >= 10_000_000:
        score += 15
    elif value >= 5_000_000:
        score += 10
    elif value >= 1_000_000:
        score += 7
    elif value >= 500_000:
        score += 5

    units = p.units or 0
    if units >= 100:
        score += 20
    elif units >= 50:
        score += 15
    elif units >= 20:
        score += 10
    elif units >= 5:
        score += 5

    if p.contractor and _norm(p.contractor) not in {"tbd", "owner/builder", "owner-builder", "homeowner"}:
        score += 5
    if p.new_construction_confidence == "MEDIUM":
        score -= 3
    return max(score, 0)
