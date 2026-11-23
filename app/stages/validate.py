"""
stages/validate.py — Stage 3: Arithmetic & field validation
Checks:
  EXT_001 — missing critical fields
  VAL_001 — line items don't sum to subtotal
  VAL_002 — subtotal + tax != total
"""

import time
from typing import Optional

from app.reconciler import reconcile_variance


def _near(a: Optional[float], b: Optional[float], tol: float = 0.02) -> bool:
    """True if a and b are within tol of each other (relative)."""
    if a is None or b is None:
        return True  # can't check
    if b == 0:
        return a == 0
    return abs(a - b) / abs(b) <= tol


def run(fields: dict, missing_critical: list[str], raw_text: str = "") -> dict:
    t0 = time.time()
    checks = []

    # EXT_001 — missing critical fields
    if missing_critical:
        checks.append({
            "rule_id": "EXT_001",
            "result": "REVIEW",
            "severity": "medium",
            "detail": f"Missing fields: {', '.join(missing_critical)}",
        })

    # VAL_001 — line items vs subtotal
    line_items = fields.get("line_items") or []
    subtotal = fields.get("subtotal")
    if line_items and subtotal is not None:
        item_sum = sum(
            float(item.get("amount") or 0) for item in line_items
            if item.get("amount") is not None
        )
        if item_sum > 0 and not _near(item_sum, subtotal):
            checks.append({
                "rule_id": "VAL_001",
                "result": "REVIEW",
                "severity": "medium",
                "expected": round(subtotal, 2),
                "actual": round(item_sum, 2),
                "variance": round(item_sum - subtotal, 2),
                "detail": f"Line items sum to {item_sum:.2f} but subtotal is {subtotal:.2f}",
            })

    # VAL_002 / VAL_003 — subtotal + tax vs total with Semantic RAG Policy Reconciliation
    total = fields.get("total")
    tax = fields.get("tax_amount") or 0.0
    if subtotal is not None and total is not None:
        expected_total = subtotal + (tax or 0)
        if not _near(expected_total, total):
            # Attempt Semantic Policy Reconciliation
            recon = reconcile_variance(
                total=total,
                subtotal=subtotal,
                tax_amount=tax,
                line_items=line_items,
                raw_text=raw_text,
                vendor_name=fields.get("vendor_name"),
            )

            if recon.get("reconciled") and recon.get("policy_id"):
                # Successfully reconciled under approved enterprise policy!
                checks.append({
                    "rule_id": "VAL_003",
                    "result": "PASS",
                    "severity": "none",
                    "policy_id": recon["policy_id"],
                    "policy_name": recon.get("policy_name"),
                    "matched_keyword": recon.get("matched_keyword"),
                    "detail": recon["detail"],
                    "expected": round(expected_total, 2),
                    "actual": round(total, 2),
                    "variance": round(recon["variance"], 2),
                })
            else:
                checks.append({
                    "rule_id": "VAL_002",
                    "result": "REVIEW",
                    "severity": "medium",
                    "expected": round(expected_total, 2),
                    "actual": round(total, 2),
                    "variance": round(total - expected_total, 2),
                    "detail": recon.get("detail", f"Subtotal ({subtotal:.2f}) + tax ({tax:.2f}) = {expected_total:.2f} but total is {total:.2f}"),
                })

    fails  = [c for c in checks if c["result"] == "REJECT"]
    warns  = [c for c in checks if c["result"] == "REVIEW"]
    status = "fail" if fails else ("warn" if warns else "ok")

    return {
        "stage": "validate",
        "status": status,
        "duration_ms": int((time.time() - t0) * 1000),
        "checks": checks,
    }
