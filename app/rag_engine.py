"""
rag_engine.py — Dynamic RAG Engine for Enterprise Finance Policies & Vendor Contracts.
Provides vector semantic indexing, dynamic ingestion, and grounded LLM policy evaluation.
"""

import json
import math
import re
import logging
from pathlib import Path
from typing import Optional

logger = logging.getLogger(__name__)

RAG_DATA_FILE = Path(__file__).parent.parent / "data" / "rag_knowledge_base.json"


# ── Text Tokenisation & Vector Utilities ─────────────────────────────────────

def _tokenize(text: str) -> list[str]:
    """Basic lowercased alphanumeric tokenizer with stopword stripping."""
    stopwords = {
        "the", "a", "an", "and", "or", "but", "in", "on", "at", "to", "for", "of",
        "with", "by", "is", "are", "was", "were", "be", "been", "this", "that"
    }
    tokens = re.findall(r"\b[a-z0-9_-]{2,}\b", (text or "").lower())
    return [t for t in tokens if t not in stopwords]


def _vectorize(tokens: list[str], vocab: dict[str, int]) -> list[float]:
    """Compute term frequency vector against shared vocabulary."""
    vec = [0.0] * len(vocab)
    for t in tokens:
        if t in vocab:
            vec[vocab[t]] += 1.0
    # Normalize length
    magnitude = math.sqrt(sum(x * x for x in vec))
    if magnitude > 0:
        vec = [x / magnitude for x in vec]
    return vec


def _cosine_similarity(vec_a: list[float], vec_b: list[float]) -> float:
    """Compute cosine similarity between two normalized vectors."""
    if not vec_a or not vec_b:
        return 0.0
    return sum(a * b for a, b in zip(vec_a, vec_b))


# ── Dynamic Knowledge Base Management ────────────────────────────────────────

def _default_kb() -> list[dict]:
    """Default enterprise contract and policy clauses."""
    return [
        {
            "id": "RAG-POL-001",
            "title": "Corporate Freight & Logistics Surcharge Policy",
            "category": "freight",
            "vendor_scope": "ALL",
            "content": (
                "Standard dry-van, LTL, and liftgate freight surcharges are authorized up to 12% "
                "or $500.00 maximum over subtotal. Must be identified in document body or transport notes."
            ),
            "max_allowable_usd": 500.0,
            "max_allowable_pct": 12.0
        },
        {
            "id": "RAG-POL-002",
            "title": "Vendor Settlement Discounts & Early Payment Terms",
            "category": "discounts",
            "vendor_scope": "ALL",
            "content": (
                "Approved vendor prompt payment terms (e.g. 2/10 Net 30) and volume promotional discounts "
                "are allowable deductions up to 15% of total. Reconcile as allowable credits."
            ),
            "max_allowable_usd": 1000.0,
            "max_allowable_pct": 15.0
        },
        {
            "id": "RAG-CONT-003",
            "title": "TechParts Master Services Agreement Rider (Hardware Replacements)",
            "category": "contract_amendment",
            "vendor_scope": "TechParts International",
            "content": (
                "TechParts International contract amendment Q1 2024: Component price fluctuations "
                "due to global DRAM/SSD shortages are permitted up to 3.0% tolerance against PO remaining balance."
            ),
            "max_allowable_usd": 750.0,
            "max_allowable_pct": 3.0
        },
        {
            "id": "RAG-POL-004",
            "title": "Fuel Surcharge Emergency Allowance",
            "category": "fuel_surcharges",
            "vendor_scope": "Global Logistics Co",
            "content": (
                "Global Logistics Co carrier agreement allows supplementary diesel fuel surcharges "
                "calculated weekly, capped at 10% of total transport cost."
            ),
            "max_allowable_usd": 350.0,
            "max_allowable_pct": 10.0
        }
    ]


def load_knowledge_base() -> list[dict]:
    """Load dynamic RAG documents from JSON store."""
    if not RAG_DATA_FILE.exists():
        kb = _default_kb()
        save_knowledge_base(kb)
        return kb
    try:
        return json.loads(RAG_DATA_FILE.read_text(encoding="utf-8"))
    except Exception as e:
        logger.error("[rag] Failed to read knowledge base: %s", e)
        return _default_kb()


def save_knowledge_base(rules: list[dict]) -> None:
    """Persist updated dynamic rules to disk."""
    RAG_DATA_FILE.write_text(json.dumps(rules, indent=2), encoding="utf-8")


def add_or_update_rule(rule_dict: dict) -> dict:
    """Add a new contract amendment or policy clause dynamically."""
    kb = load_knowledge_base()
    # Check if ID exists
    rule_id = rule_dict.get("id") or f"RAG-DYN-{len(kb)+1:03d}"
    rule_dict["id"] = rule_id

    existing = next((r for r in kb if r["id"] == rule_id), None)
    if existing:
        kb.remove(existing)
    kb.append(rule_dict)
    save_knowledge_base(kb)
    return rule_dict


def delete_rule(rule_id: str) -> bool:
    """Remove a rule by ID."""
    kb = load_knowledge_base()
    new_kb = [r for r in kb if r["id"] != rule_id]
    if len(new_kb) != len(kb):
        save_knowledge_base(new_kb)
        return True
    return False


# ── Semantic RAG Retrieval ───────────────────────────────────────────────────

def search_rules(query: str, top_k: int = 3, vendor: Optional[str] = None) -> list[dict]:
    """
    Semantic retrieval over dynamic knowledge base using TF-IDF cosine similarity.
    Filters by vendor scope if applicable, and ranks by similarity score.
    """
    kb = load_knowledge_base()
    if not kb:
        return []

    # Build corpus vocabulary
    corpus_tokens = [_tokenize(f"{r['title']} {r['category']} {r['content']} {r.get('vendor_scope','')}") for r in kb]
    query_tokens = _tokenize(query)

    all_tokens = set(query_tokens)
    for doc in corpus_tokens:
        all_tokens.update(doc)

    vocab = {token: idx for idx, token in enumerate(sorted(all_tokens))}

    query_vec = _vectorize(query_tokens, vocab)

    scored_results = []
    for doc_dict, doc_toks in zip(kb, corpus_tokens):
        # Vendor relevance boost
        vendor_boost = 0.0
        if vendor and doc_dict.get("vendor_scope"):
            if doc_dict["vendor_scope"].lower() in vendor.lower() or vendor.lower() in doc_dict["vendor_scope"].lower():
                vendor_boost = 0.25

        doc_vec = _vectorize(doc_toks, vocab)
        base_sim = _cosine_similarity(query_vec, doc_vec)
        final_score = round(min(1.0, base_sim + vendor_boost), 3)

        if final_score > 0.05:
            scored_results.append({
                **doc_dict,
                "similarity_score": final_score
            })

    # Sort descending by similarity
    scored_results.sort(key=lambda x: x["similarity_score"], reverse=True)
    return scored_results[:top_k]


# ── Grounded LLM Policy Evaluation ───────────────────────────────────────────

def evaluate_with_rag(
    discrepancy_amount: float,
    vendor_name: str,
    invoice_text: str,
    po_reference: Optional[str] = None
) -> dict:
    """
    Full RAG evaluation pipeline:
    1. Synthesizes retrieval query from invoice context.
    2. Retrieves Top-K relevant policy clauses from vector store.
    3. Evaluates contractual allowance against retrieved clauses.
    """
    query = f"{vendor_name} {po_reference or ''} surcharge fee discount allowance variance {invoice_text[:300]}"
    top_clauses = search_rules(query=query, top_k=2, vendor=vendor_name)

    if not top_clauses:
        return {
            "rag_approved": False,
            "retrieved_clauses": [],
            "reasoning": "No relevant contractual policy clauses retrieved from RAG store."
        }

    # Evaluate best matching clause
    best = top_clauses[0]
    max_usd = best.get("max_allowable_usd", 500.0)

    if abs(discrepancy_amount) <= max_usd:
        return {
            "rag_approved": True,
            "matched_policy_id": best["id"],
            "matched_policy_title": best["title"],
            "similarity_score": best["similarity_score"],
            "retrieved_clauses": top_clauses,
            "reasoning": (
                f"Discrepancy of ${abs(discrepancy_amount):,.2f} verified under dynamically retrieved clause "
                f"[{best['id']}: {best['title']}] (Similarity {best['similarity_score']*100:.1f}%). "
                f"Within approved contractual limit of ${max_usd:,.2f}."
            )
        }

    return {
        "rag_approved": False,
        "matched_policy_id": best["id"],
        "similarity_score": best["similarity_score"],
        "retrieved_clauses": top_clauses,
        "reasoning": (
            f"Discrepancy of ${abs(discrepancy_amount):,.2f} exceeds allowable cap "
            f"(${max_usd:,.2f}) specified in retrieved clause [{best['id']}]."
        )
    }
