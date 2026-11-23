"""
pipeline.py — Orchestrates all 8 stages and emits SSE events.
Each stage result is both stored in DB and yielded as an SSE event.
"""

import json
import time
import uuid
import yaml
import logging
from pathlib import Path
from typing import AsyncGenerator

from app.db import (
    init_db, insert_run, update_run, insert_event, insert_audit,
    record_invoice_seen,
)
from app.stages import ingest, extract, validate, vendor, duplicate, po_match, tolerance, decide

logger = logging.getLogger(__name__)

RULES_PATH = Path(__file__).parent / "rules.yaml"


def load_rules() -> dict:
    with open(RULES_PATH) as f:
        return yaml.safe_load(f)


def _sse(event_type: str, data: dict) -> str:
    """Format a Server-Sent Event string."""
    return f"event: {event_type}\ndata: {json.dumps(data)}\n\n"


async def run_pipeline(file_bytes: bytes, filename: str) -> AsyncGenerator[str, None]:
    """
    Async generator that runs all stages and yields SSE events.
    Consumers: FastAPI StreamingResponse.
    """
    run_id = f"r_{uuid.uuid4().hex[:8]}"
    rules  = load_rules()

    # Initialise run record
    insert_run(run_id, filename)
    yield _sse("run_start", {"run_id": run_id, "filename": filename, "timestamp": time.time()})

    # Collect all stage results for the decision stage
    all_stage_results = []
    final_fields = {}
    missing_critical = []
    vendor_id = None
    po_remaining = None

    try:
        # ── Stage 1: Ingest ──────────────────────────────────────────────────
        yield _sse("stage_start", {"stage": "ingest", "run_id": run_id})
        ingest_result = ingest.run(file_bytes, filename, run_id)
        insert_event(run_id, "ingest", ingest_result["status"], ingest_result, ingest_result["duration_ms"])
        yield _sse("stage_done", ingest_result)
        all_stage_results.append(ingest_result)

        file_hash = ingest_result["file_hash"]
        pdf_type  = ingest_result["pdf_type"]

        # ── Stage 2: Extract ─────────────────────────────────────────────────
        yield _sse("stage_start", {"stage": "extract", "run_id": run_id})
        extract_result = extract.run(file_bytes, file_hash, pdf_type)
        insert_event(run_id, "extract", extract_result["status"], extract_result, extract_result["duration_ms"])
        yield _sse("stage_done", extract_result)
        all_stage_results.append(extract_result)

        final_fields     = extract_result["fields"]
        missing_critical = extract_result["missing_critical"]

        # ── Stage 3: Validate ────────────────────────────────────────────────
        yield _sse("stage_start", {"stage": "validate", "run_id": run_id})
        validate_result = validate.run(
            final_fields,
            missing_critical,
            raw_text=extract_result.get("raw_text", "")
        )
        insert_event(run_id, "validate", validate_result["status"], validate_result, validate_result["duration_ms"])
        yield _sse("stage_done", validate_result)
        all_stage_results.append(validate_result)

        # ── Stage 4: Vendor check ────────────────────────────────────────────
        yield _sse("stage_start", {"stage": "vendor_check", "run_id": run_id})
        vendor_result = vendor.run(final_fields, rules)
        insert_event(run_id, "vendor_check", vendor_result["status"], vendor_result, vendor_result["duration_ms"])
        yield _sse("stage_done", vendor_result)
        all_stage_results.append(vendor_result)

        vendor_id = vendor_result.get("matched_vendor_id")

        # ── Stage 5: Duplicate check ─────────────────────────────────────────
        yield _sse("stage_start", {"stage": "duplicate_check", "run_id": run_id})
        dup_result = duplicate.run(file_hash, final_fields, vendor_id, rules)
        insert_event(run_id, "duplicate_check", dup_result["status"], dup_result, dup_result["duration_ms"])
        yield _sse("stage_done", dup_result)
        all_stage_results.append(dup_result)

        # ── Stage 6: PO match ────────────────────────────────────────────────
        yield _sse("stage_start", {"stage": "po_match", "run_id": run_id})
        po_result = po_match.run(final_fields, vendor_id, rules)
        insert_event(run_id, "po_match", po_result["status"], po_result, po_result["duration_ms"])
        yield _sse("stage_done", po_result)
        all_stage_results.append(po_result)

        po_remaining = po_result.get("po_remaining")

        # ── Stage 7: Tolerance check ─────────────────────────────────────────
        yield _sse("stage_start", {"stage": "tolerance_check", "run_id": run_id})
        tol_result = tolerance.run(final_fields, po_remaining, vendor_id, rules)
        insert_event(run_id, "tolerance_check", tol_result["status"], tol_result, tol_result["duration_ms"])
        yield _sse("stage_done", tol_result)
        all_stage_results.append(tol_result)

        # ── Stage 8: Decision ────────────────────────────────────────────────
        yield _sse("stage_start", {"stage": "decision", "run_id": run_id})
        decision_result = decide.run(all_stage_results, final_fields, missing_critical)
        insert_event(run_id, "decision", decision_result["status"], decision_result, decision_result["duration_ms"])
        yield _sse("stage_done", decision_result)

        # ── Finalise run ─────────────────────────────────────────────────────
        decision = decision_result["decision"]
        update_run(run_id, "done", decision, decision_result["primary_reason"])

        # Record the invoice in history (for future duplicate detection)
        record_invoice_seen(
            file_hash=file_hash,
            vendor_id=vendor_id,
            invoice_no=final_fields.get("invoice_number"),
            total=final_fields.get("total"),
            invoice_date=final_fields.get("invoice_date"),
            run_id=run_id,
        )

        # Audit entry
        insert_audit(
            run_id=run_id,
            model=f"groq/{__import__('os').getenv('GROQ_MODEL', 'llama-3.1-8b-instant')}",
            rules_version=rules.get("version", "unknown"),
            config_snapshot=rules,
        )

        yield _sse("run_done", {
            "run_id": run_id,
            "decision": decision,
            "decision_label": decision_result["decision_label"],
            "primary_reason": decision_result["primary_reason"],
            "counterfactual": decision_result.get("counterfactual"),
            "vendor_email_draft": decision_result.get("vendor_email_draft"),
        })

    except Exception as exc:
        logger.exception("[pipeline] unhandled error in run %s", run_id)
        update_run(run_id, "error")
        yield _sse("run_error", {
            "run_id": run_id,
            "error": str(exc),
        })
