"""
stages/vendor.py — Stage 4: Vendor lookup and fuzzy match
Checks:
  VND_001 — vendor not in master (REJECT)
  VND_002 — fuzzy match below threshold (REVIEW)
"""

import time
import json
import logging
from typing import Optional

from rapidfuzz import fuzz, process

from app.db import get_all_vendors

logger = logging.getLogger(__name__)


def _candidate_names(vendor: dict) -> list[str]:
    """Return canonical name + all aliases for a vendor record."""
    names = [vendor["name"]]
    try:
        aliases = json.loads(vendor.get("aliases") or "[]")
        names.extend(aliases)
    except (json.JSONDecodeError, TypeError):
        pass
    return names


def find_vendor(vendor_name: Optional[str], rules: dict) -> dict:
    """
    Returns a dict with:
      matched_vendor_id, matched_vendor_name, match_score, match_method, check
    """
    ok_threshold     = rules["vendor"]["match_ok_threshold"]
    review_threshold = rules["vendor"]["match_review_threshold"]

    if not vendor_name:
        return {
            "matched_vendor_id": None,
            "matched_vendor_name": None,
            "match_score": 0,
            "match_method": "none",
            "check": {
                "rule_id": "VND_001",
                "result": "REJECT",
                "severity": "high",
                "detail": "No vendor name on invoice",
            },
        }

    vendors = get_all_vendors()
    if not vendors:
        logger.warning("[vendor] no vendors in master — routing to REVIEW")
        return {
            "matched_vendor_id": None,
            "matched_vendor_name": None,
            "match_score": 0,
            "match_method": "empty_master",
            "check": {
                "rule_id": "VND_002",
                "result": "REVIEW",
                "severity": "medium",
                "detail": "Vendor master is empty",
            },
        }

    # Build a flat list of (name_string, vendor_id) for fuzzy matching
    choices = []
    for v in vendors:
        for name in _candidate_names(v):
            choices.append((name, v["id"], v["name"], v["status"]))

    # Find best fuzzy match
    best_score = 0
    best_vendor_id = None
    best_vendor_name = None
    best_matched_alias = None
    best_status = None

    for alias, vid, canonical, vstatus in choices:
        score = max(
            fuzz.token_set_ratio(vendor_name.lower(), alias.lower()),
            fuzz.token_sort_ratio(vendor_name.lower(), alias.lower())
        )
        if score > best_score:
            best_score = score
            best_vendor_id = vid
            best_vendor_name = canonical
            best_matched_alias = alias
            best_status = vstatus

    # Exact match wins unconditionally
    if best_score >= ok_threshold:
        if best_status == "blocked":
            return {
                "matched_vendor_id": best_vendor_id,
                "matched_vendor_name": best_vendor_name,
                "match_score": best_score,
                "match_method": "fuzzy_ok",
                "check": {
                    "rule_id": "VND_001",
                    "result": "REJECT",
                    "severity": "high",
                    "detail": f"Vendor '{best_vendor_name}' is blocked",
                },
            }
        return {
            "matched_vendor_id": best_vendor_id,
            "matched_vendor_name": best_vendor_name,
            "match_score": best_score,
            "match_method": "fuzzy_ok",
            "matched_alias": best_matched_alias,
            "check": {
                "rule_id": None,
                "result": "PASS",
                "severity": "none",
                "detail": f"Matched '{best_vendor_name}' (score {best_score})",
            },
        }

    if best_score >= review_threshold:
        return {
            "matched_vendor_id": best_vendor_id,
            "matched_vendor_name": best_vendor_name,
            "match_score": best_score,
            "match_method": "fuzzy_review",
            "check": {
                "rule_id": "VND_002",
                "result": "REVIEW",
                "severity": "medium",
                "detail": f"Best vendor match '{best_vendor_name}' has score {best_score} (threshold {ok_threshold})",
            },
        }

    return {
        "matched_vendor_id": None,
        "matched_vendor_name": None,
        "match_score": best_score,
        "match_method": "no_match",
        "check": {
            "rule_id": "VND_001",
            "result": "REJECT",
            "severity": "high",
            "detail": f"No vendor match found for '{vendor_name}' (best score {best_score})",
        },
    }


def run(fields: dict, rules: dict) -> dict:
    t0 = time.time()

    vendor_name = fields.get("vendor_name")
    result = find_vendor(vendor_name, rules)

    check = result["check"]
    status = "fail" if check["result"] == "REJECT" else (
        "warn" if check["result"] == "REVIEW" else "ok"
    )

    return {
        "stage": "vendor_check",
        "status": status,
        "duration_ms": int((time.time() - t0) * 1000),
        "invoice_vendor_name": vendor_name,
        "matched_vendor_id": result.get("matched_vendor_id"),
        "matched_vendor_name": result.get("matched_vendor_name"),
        "match_score": result.get("match_score"),
        "match_method": result.get("match_method"),
        "checks": [check],
    }
