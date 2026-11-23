"""
stages/duplicate.py — Stage 5: Duplicate detection
Checks:
  DUP_001 — exact duplicate (file hash OR vendor+invoice_number)
  DUP_002 — near-duplicate (same vendor+amount+date, invoice_no within edit distance 2)
"""

import time
from typing import Optional

from rapidfuzz.distance import Levenshtein

from app.db import find_prior_invoice


def run(
    file_hash: str,
    fields: dict,
    vendor_id: Optional[int],
    rules: dict,
) -> dict:
    t0 = time.time()
    checks = []

    invoice_no   = fields.get("invoice_number")
    total        = fields.get("total")
    invoice_date = fields.get("invoice_date")
    edit_dist_threshold = rules["duplicate"]["invoice_no_edit_distance"]

    exact_hash, exact_inv, near = find_prior_invoice(
        file_hash=file_hash,
        vendor_id=vendor_id or -1,
        invoice_no=invoice_no,
        total=total,
        invoice_date=invoice_date,
    )

    if exact_hash:
        checks.append({
            "rule_id": "DUP_001",
            "result": "REJECT",
            "severity": "high",
            "detail": f"Exact file match — previously submitted as run {exact_hash['run_id']}",
            "prior_run_id": exact_hash["run_id"],
        })
    elif exact_inv:
        checks.append({
            "rule_id": "DUP_001",
            "result": "REJECT",
            "severity": "high",
            "detail": f"Invoice number '{invoice_no}' already exists for this vendor (run {exact_inv['run_id']})",
            "prior_run_id": exact_inv["run_id"],
        })
    elif near:
        # Check edit distance on invoice number
        prior_inv_no = near.get("invoice_no") or ""
        current_inv_no = invoice_no or ""
        dist = Levenshtein.distance(prior_inv_no, current_inv_no) if prior_inv_no and current_inv_no else 99
        if dist <= edit_dist_threshold:
            checks.append({
                "rule_id": "DUP_002",
                "result": "REVIEW",
                "severity": "high",
                "detail": (
                    f"Near-duplicate detected: same vendor, amount ({total}), date ({invoice_date}), "
                    f"invoice_no differs by {dist} character(s) from '{prior_inv_no}' (run {near['run_id']})"
                ),
                "prior_run_id": near["run_id"],
                "edit_distance": dist,
            })

    fails  = [c for c in checks if c["result"] == "REJECT"]
    warns  = [c for c in checks if c["result"] == "REVIEW"]
    status = "fail" if fails else ("warn" if warns else "ok")

    return {
        "stage": "duplicate_check",
        "status": status,
        "duration_ms": int((time.time() - t0) * 1000),
        "checks": checks,
        "is_new": status == "ok",
    }
