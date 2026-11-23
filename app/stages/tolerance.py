"""
stages/tolerance.py — Stage 7: Tolerance check
Checks invoice total vs PO remaining balance.
  TOL_001 — within tolerance: PASS
  TOL_002 — in review band: REVIEW
  TOL_003 — above upper band: REJECT
Tolerance thresholds come from rules.yaml, with per-vendor overrides.
"""

import time
from typing import Optional

from app.db import get_vendor_by_id


def _get_vendor_tolerance(vendor_id: Optional[int], rules: dict) -> float:
    """Return per-vendor tolerance_pct if set, else default from rules."""
    if vendor_id:
        vendor = get_vendor_by_id(vendor_id)
        if vendor and vendor.get("tolerance_pct") is not None:
            return float(vendor["tolerance_pct"])
    return float(rules["tolerance"]["default_ok_pct"])


def run(
    fields: dict,
    po_remaining: Optional[float],
    vendor_id: Optional[int],
    rules: dict,
) -> dict:
    t0 = time.time()
    checks = []

    invoice_total = fields.get("total")
    review_pct    = float(rules["tolerance"]["default_review_pct"])

    if invoice_total is None or po_remaining is None:
        # Can't check without both values
        return {
            "stage": "tolerance_check",
            "status": "warn",
            "duration_ms": int((time.time() - t0) * 1000),
            "checks": [{
                "rule_id": "TOL_002",
                "result": "REVIEW",
                "severity": "low",
                "detail": "Cannot run tolerance check — missing invoice total or PO remaining balance",
            }],
        }

    ok_pct = _get_vendor_tolerance(vendor_id, rules)

    if po_remaining <= 0:
        # PO is fully consumed
        checks.append({
            "rule_id": "TOL_003",
            "result": "REJECT",
            "severity": "high",
            "detail": f"PO is fully consumed (remaining balance: $0.00). Invoice total: ${invoice_total:,.2f}",
            "invoice_total": invoice_total,
            "po_remaining": po_remaining,
            "variance_pct": None,
        })
    elif invoice_total <= po_remaining:
        # Fully covered by PO remaining balance
        var_pct = ((invoice_total - po_remaining) / po_remaining) * 100
        checks.append({
            "rule_id": "TOL_001",
            "result": "PASS",
            "severity": "none",
            "detail": f"Invoice amount (${invoice_total:,.2f}) within PO remaining balance (${po_remaining:,.2f})",
            "invoice_total": invoice_total,
            "po_remaining": po_remaining,
            "variance_pct": round(var_pct, 2),
        })
    else:
        # Overrun: invoice total exceeds PO remaining balance
        variance_pct = ((invoice_total - po_remaining) / po_remaining) * 100

        if variance_pct <= ok_pct:
            checks.append({
                "rule_id": "TOL_001",
                "result": "PASS",
                "severity": "none",
                "detail": f"Amount slightly exceeds PO but within {ok_pct}% tolerance (+{variance_pct:.2f}%)",
                "invoice_total": invoice_total,
                "po_remaining": po_remaining,
                "variance_pct": round(variance_pct, 2),
            })
        elif variance_pct <= review_pct:
            checks.append({
                "rule_id": "TOL_002",
                "result": "REVIEW",
                "severity": "medium",
                "detail": f"Amount exceeds PO by {variance_pct:+.2f}% (tolerance band: {ok_pct}%-{review_pct}%)",
                "invoice_total": invoice_total,
                "po_remaining": po_remaining,
                "variance_pct": round(variance_pct, 2),
                "counterfactual": f"Would auto-approve if total were ≤ {po_remaining * (1 + ok_pct/100):.2f}",
            })
        else:
            checks.append({
                "rule_id": "TOL_003",
                "result": "REJECT",
                "severity": "high",
                "detail": f"Amount exceeds PO by {variance_pct:+.2f}% (exceeds {review_pct}% upper limit)",
                "invoice_total": invoice_total,
                "po_remaining": po_remaining,
                "variance_pct": round(variance_pct, 2),
                "counterfactual": f"Would route to review if total were ≤ {po_remaining * (1 + review_pct/100):.2f}",
            })

    fails  = [c for c in checks if c["result"] == "REJECT"]
    warns  = [c for c in checks if c["result"] == "REVIEW"]
    status = "fail" if fails else ("warn" if warns else "ok")

    return {
        "stage": "tolerance_check",
        "status": status,
        "duration_ms": int((time.time() - t0) * 1000),
        "invoice_total": invoice_total,
        "po_remaining": po_remaining,
        "ok_pct": ok_pct,
        "review_pct": review_pct,
        "checks": checks,
    }
