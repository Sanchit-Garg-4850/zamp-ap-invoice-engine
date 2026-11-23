"""
reconciler.py — Semantic Finance Policy Reconciliation Engine (RAG Utility)
Cross-references invoice mathematical variances against enterprise financial policy rulesets.
"""

import json
import re
import logging
from pathlib import Path
from typing import Optional

logger = logging.getLogger(__name__)

POLICY_FILE = Path(__file__).parent.parent / "data" / "finance_policies.json"


def load_policies() -> list[dict]:
    """Load mutable enterprise finance policies."""
    if not POLICY_FILE.exists():
        return []
    try:
        data = json.loads(POLICY_FILE.read_text(encoding="utf-8"))
        return data.get("policies", [])
    except Exception as e:
        logger.error("[reconciler] Failed to load finance policies: %s", e)
        return []


def reconcile_variance(
    total: Optional[float],
    subtotal: Optional[float],
    tax_amount: Optional[float],
    line_items: list[dict],
    raw_text: str,
    vendor_name: Optional[str] = None
) -> dict:
    """
    Evaluates whether an apparent arithmetic variance is accounted for by 
    enterprise policy allowances (e.g. unbundled freight, discounts, fuel surcharges).
    """
    if total is None or subtotal is None:
        return {"reconciled": False, "reason": "Missing subtotal or total values"}

    expected_total = subtotal + (tax_amount or 0.0)
    variance = round(total - expected_total, 2)

    # If within 2 cents, naturally balanced (floating point rounding)
    if abs(variance) <= 0.02:
        return {
            "reconciled": True,
            "variance": 0.0,
            "policy_applied": None,
            "note": "Exact arithmetic match"
        }

    policies = load_policies()
    text_lower = (raw_text or "").lower()

    # Search applicable policies
    for pol in policies:
        policy_id = pol["policy_id"]
        max_pct = pol.get("max_allowance_pct", 10.0)
        max_usd = pol.get("max_allowance_usd", 500.0)
        keywords = pol.get("keywords", [])

        # Check percentage variance
        pct_variance = abs(variance / subtotal * 100) if subtotal > 0 else 999.0
        if pct_variance > max_pct or abs(variance) > max_usd:
            continue

        # Look for semantic keyword evidence in document text
        matched_kw = None
        for kw in keywords:
            if kw.lower() in text_lower:
                matched_kw = kw
                break

        if matched_kw:
            # Policy rule satisfied!
            adjustment_type = "surcharge" if variance > 0 else "discount"
            logger.info(
                "[reconciler] Variance of $%s reconciled under %s via '%s'",
                variance, policy_id, matched_kw
            )
            return {
                "reconciled": True,
                "variance": variance,
                "policy_id": policy_id,
                "policy_name": pol["name"],
                "matched_keyword": matched_kw,
                "adjustment_type": adjustment_type,
                "detail": (
                    f"Discrepancy of ${abs(variance):,.2f} verified as valid {adjustment_type} "
                    f"('{matched_kw}') under Policy {policy_id} ({pol['name']})."
                )
            }

    # If static keyword policies didn't resolve it, query dynamic RAG Vector Knowledge Base
    try:
        from app.rag_engine import evaluate_with_rag
        rag_res = evaluate_with_rag(
            discrepancy_amount=variance,
            vendor_name=vendor_name or "",
            invoice_text=raw_text,
        )
        if rag_res.get("rag_approved"):
            logger.info(
                "[reconciler] Variance of $%s reconciled via RAG Clause [%s] (%s)",
                variance, rag_res["matched_policy_id"], rag_res.get("matched_policy_title")
            )
            return {
                "reconciled": True,
                "variance": variance,
                "policy_id": rag_res["matched_policy_id"],
                "policy_name": rag_res.get("matched_policy_title"),
                "matched_keyword": f"RAG Vector ({rag_res['similarity_score']*100:.0f}%)",
                "adjustment_type": "rag_allowance",
                "detail": rag_res["reasoning"],
                "retrieved_clauses": rag_res.get("retrieved_clauses", []),
            }
    except Exception as e:
        logger.warning("[reconciler] RAG evaluation failed: %s", e)

    # Not covered by any approved policy
    return {
        "reconciled": False,
        "reconciled": False,
        "variance": variance,
        "detail": (
            f"Unreconciled variance of ${abs(variance):,.2f} detected "
            f"(Subtotal ${subtotal:,.2f} + Tax ${tax_amount or 0:,.2f} != Total ${total:,.2f}). "
            f"No matching finance policy allowance identified."
        )
    }
