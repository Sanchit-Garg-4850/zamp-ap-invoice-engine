"""
stages/decide.py — Stage 8: Decision engine
Implements the ordered ladder from Master_LLM.md D7:
  1. Any REJECT → final decision: REJECT
  2. Any REVIEW  → final decision: NEEDS_REVIEW
  3. Otherwise   → final decision: AUTO_APPROVE

Also builds:
  - Decision trace (which rule drove the outcome)
  - Counterfactual (what would flip it)
  - Vendor email draft if needed
"""

import time
from typing import Optional


DECISION_LABELS = {
    "AUTO_APPROVE":  "✅ AUTO APPROVE",
    "NEEDS_REVIEW":  "⚠️ NEEDS REVIEW",
    "REJECT":        "❌ REJECT",
}


def _collect_checks(stage_results: list[dict]) -> tuple[list, list]:
    """Gather all REJECT and REVIEW checks across all stages."""
    rejects = []
    reviews = []
    for stage in stage_results:
        for check in stage.get("checks", []):
            if check.get("result") == "REJECT":
                rejects.append({**check, "stage": stage["stage"]})
            elif check.get("result") == "REVIEW":
                reviews.append({**check, "stage": stage["stage"]})
    return rejects, reviews


def _primary_reason(rejects: list, reviews: list) -> str:
    if rejects:
        return rejects[0].get("rule_id", "UNKNOWN")
    if reviews:
        return reviews[0].get("rule_id", "UNKNOWN")
    return "ALL_PASS"


def _counterfactual(decision: str, rejects: list, reviews: list) -> Optional[str]:
    """
    Return a single human-readable sentence explaining what would change the decision.
    """
    if decision == "AUTO_APPROVE":
        return None
    if decision == "REJECT":
        rule = rejects[0] if rejects else None
        if rule:
            cf = rule.get("counterfactual")
            if cf:
                return cf
            return f"Would route to review if rule {rule['rule_id']} were resolved."
    if decision == "NEEDS_REVIEW":
        rule = reviews[0] if reviews else None
        if rule:
            cf = rule.get("counterfactual")
            if cf:
                return cf
        return "Would auto-approve if all warnings were resolved."
    return None


def _build_vendor_email(fields: dict, missing_critical: list[str], checks: list) -> Optional[str]:
    """
    Generate a vendor email draft when information is missing (EXT_001 or PO_001).
    """
    needs_email = any(
        c.get("rule_id") in ("EXT_001", "PO_001") for c in checks
    )
    if not needs_email:
        return None

    vendor = fields.get("vendor_name") or "Vendor"
    invoice_no = fields.get("invoice_number") or "[invoice number not found]"
    missing_lines = []
    if "invoice_number" in missing_critical:
        missing_lines.append("- Invoice number")
    if "invoice_date" in missing_critical:
        missing_lines.append("- Invoice date")
    if "total" in missing_critical:
        missing_lines.append("- Invoice total amount")
    po_issues = [c for c in checks if c.get("rule_id") in ("PO_001", "PO_002")]
    if po_issues:
        missing_lines.append("- Purchase Order (PO) reference number")

    if not missing_lines:
        return None

    return f"""Subject: Action Required — Invoice {invoice_no} Requires Additional Information

Dear {vendor},

Thank you for submitting invoice {invoice_no}. During our automated review, 
we identified the following missing information that is required to process your invoice:

{chr(10).join(missing_lines)}

Please resubmit your invoice with the above information included. If you have any 
questions, please contact our AP team.

Best regards,
AP Automation System"""


def run(stage_results: list[dict], fields: dict, missing_critical: list[str]) -> dict:
    t0 = time.time()

    rejects, reviews = _collect_checks(stage_results)
    all_checks = rejects + reviews

    if rejects:
        decision = "REJECT"
    elif reviews:
        decision = "NEEDS_REVIEW"
    else:
        decision = "AUTO_APPROVE"

    primary_reason = _primary_reason(rejects, reviews)
    counterfactual = _counterfactual(decision, rejects, reviews)
    vendor_email   = _build_vendor_email(fields, missing_critical, all_checks)

    # Build the decision trace (the ladder, made visible)
    trace_lines = [
        f"Hard fails (REJECT rules): {len(rejects)} — {[r['rule_id'] for r in rejects] or 'none'}",
        f"Warnings (REVIEW rules):   {len(reviews)} — {[r['rule_id'] for r in reviews] or 'none'}",
        f"Decision ladder result:    {decision}",
    ]
    if counterfactual:
        trace_lines.append(f"Counterfactual:            {counterfactual}")

    return {
        "stage": "decision",
        "status": "ok",
        "duration_ms": int((time.time() - t0) * 1000),
        "decision": decision,
        "decision_label": DECISION_LABELS[decision],
        "primary_reason": primary_reason,
        "reject_checks": rejects,
        "review_checks": reviews,
        "decision_trace": trace_lines,
        "counterfactual": counterfactual,
        "vendor_email_draft": vendor_email,
        "checks": [],   # decision stage itself emits no new checks
    }
