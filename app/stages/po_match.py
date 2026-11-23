"""
stages/po_match.py — Stage 6: PO matching
Strategy (per Master_LLM.md D6):
  1. Explicit PO reference on invoice → direct lookup
  2. No reference → ranked candidate match (vendor + amount scoring)
  3. Track remaining balance for split-PO scenarios
Checks: PO_001, PO_002
"""

import time
import logging
from typing import Optional

from app.db import get_po, get_pos_for_vendor, get_invoices_for_po, get_po_lines

logger = logging.getLogger(__name__)


def _compute_remaining_balance(po_number: str, po_total: float) -> float:
    """Sum approved invoices already matched to this PO, return remaining."""
    prior = get_invoices_for_po(po_number)
    already_billed = sum(float(r.get("total") or 0) for r in prior)
    return round(po_total - already_billed, 2)


def _score_candidate(po: dict, invoice_total: Optional[float],
                      po_remaining: float, rules: dict) -> int:
    """Score a PO candidate 0-100."""
    score = 0
    amount_weight = rules["po_match"]["amount_weight"]
    if invoice_total and po_remaining > 0:
        ratio = invoice_total / po_remaining
        # Closeness to remaining balance
        if 0.90 <= ratio <= 1.10:
            score += amount_weight
        elif 0.75 <= ratio <= 1.25:
            score += amount_weight // 2
    return score


def run(
    fields: dict,
    vendor_id: Optional[int],
    rules: dict,
) -> dict:
    t0 = time.time()

    po_ref        = fields.get("po_reference")
    invoice_total = fields.get("total")
    min_conf      = rules["po_match"]["min_confidence"]
    explicit_bonus = rules["po_match"]["explicit_ref_weight"]

    matched_po = None
    po_remaining = None
    confidence = 0
    match_method = "none"
    checks = []

    # ── Path 1: Explicit PO reference ──────────────────────────────────────────
    if po_ref:
        po = get_po(po_ref)
        if po and (vendor_id is None or po["vendor_id"] == vendor_id):
            po_remaining = _compute_remaining_balance(po["po_number"], po["total"])
            confidence = 50 + explicit_bonus  # up to 100
            matched_po = po
            match_method = "explicit"
            logger.info("[po_match] explicit match: %s", po_ref)
        elif po:
            # PO exists but vendor doesn't match
            po_remaining = _compute_remaining_balance(po["po_number"], po["total"])
            confidence = 40
            matched_po = po
            match_method = "explicit_vendor_mismatch"
            checks.append({
                "rule_id": "PO_002",
                "result": "REVIEW",
                "severity": "medium",
                "detail": f"PO {po_ref} found but vendor on PO (id={po['vendor_id']}) differs from invoice vendor (id={vendor_id})",
            })
        else:
            # PO reference given but not found in system
            checks.append({
                "rule_id": "PO_001",
                "result": "REVIEW",
                "severity": "medium",
                "detail": f"PO reference '{po_ref}' not found in system",
            })
            match_method = "explicit_not_found"

    # ── Path 2: Implied match (no explicit PO ref, or ref not found) ───────────
    if matched_po is None and vendor_id:
        vendor_pos = get_pos_for_vendor(vendor_id)
        best_po = None
        best_score = 0

        for po in vendor_pos:
            remaining = _compute_remaining_balance(po["po_number"], po["total"])
            score = _score_candidate(po, invoice_total, remaining, rules)
            score += rules["po_match"]["vendor_weight"]  # vendor matches because we filtered
            if score > best_score:
                best_score = score
                best_po = po
                po_remaining = remaining

        if best_po and best_score >= min_conf:
            matched_po = best_po
            confidence = best_score
            match_method = "implied"
            checks.append({
                "rule_id": "PO_002",
                "result": "REVIEW",
                "severity": "low",
                "detail": f"No explicit PO reference. Implied match to {best_po['po_number']} (confidence {best_score})",
            })
        else:
            confidence = best_score if best_po else 0
            match_method = "no_match"
            checks.append({
                "rule_id": "PO_001",
                "result": "REVIEW",
                "severity": "medium",
                "detail": "No confident PO match found" + (
                    f" (best candidate scored {best_score}/{min_conf} required)" if best_po else ""
                ),
            })

    elif matched_po is None and not vendor_id:
        checks.append({
            "rule_id": "PO_001",
            "result": "REVIEW",
            "severity": "high",
            "detail": "Cannot attempt implied PO match — vendor not identified",
        })

    fails  = [c for c in checks if c["result"] == "REJECT"]
    warns  = [c for c in checks if c["result"] == "REVIEW"]
    # If we have a confident explicit match and no other checks fired, it's ok
    if matched_po and not checks:
        status = "ok"
    else:
        status = "fail" if fails else ("warn" if warns else "ok")

    po_lines = get_po_lines(matched_po["po_number"]) if matched_po else []

    return {
        "stage": "po_match",
        "status": status,
        "duration_ms": int((time.time() - t0) * 1000),
        "matched_po": matched_po["po_number"] if matched_po else None,
        "po_total": matched_po["total"] if matched_po else None,
        "po_remaining": po_remaining,
        "po_lines": po_lines,
        "match_method": match_method,
        "confidence": confidence,
        "checks": checks,
    }
