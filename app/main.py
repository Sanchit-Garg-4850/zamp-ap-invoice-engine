"""
main.py — FastAPI application.
Routes:
  POST /api/run          → upload PDF, stream pipeline events via SSE
  GET  /api/runs         → dashboard history
  GET  /api/runs/{id}    → single run detail
  POST /api/runs/{id}/override  → reviewer override
  GET  /                 → run view UI
  GET  /dashboard        → dashboard UI
"""

import os
import logging
import json
from pathlib import Path
from contextlib import asynccontextmanager

from fastapi import FastAPI, UploadFile, File, HTTPException
from fastapi.responses import HTMLResponse, StreamingResponse, JSONResponse, FileResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

from app.db import init_db, get_runs, get_run, get_run_events, insert_override
from app.pipeline import run_pipeline
from scripts.seed import seed

logging.basicConfig(level=logging.INFO, format="%(levelname)s %(name)s — %(message)s")
logger = logging.getLogger(__name__)

STATIC_DIR = Path(__file__).parent.parent / "static"


@asynccontextmanager
async def lifespan(app: FastAPI):
    init_db()
    logger.info("[startup] DB initialised")
    yield


app = FastAPI(title="Invoice Processor", version="1.0.0", lifespan=lifespan)
app.mount("/static", StaticFiles(directory=str(STATIC_DIR)), name="static")


INVOICES_DIR = Path(__file__).parent.parent / "data" / "invoices"
POLICIES_PATH = Path(__file__).parent.parent / "data" / "finance_policies.json"


# ── UI routes ─────────────────────────────────────────────────────────────────

@app.get("/", response_class=HTMLResponse)
async def run_view():
    return (STATIC_DIR / "run.html").read_text(encoding="utf-8")


@app.get("/dashboard", response_class=HTMLResponse)
async def dashboard_view():
    return (STATIC_DIR / "dashboard.html").read_text(encoding="utf-8")


# ── API routes ────────────────────────────────────────────────────────────────

@app.post("/api/run-sample/{filename}")
async def start_sample_run(filename: str):
    """Run one of the prepared demo invoice PDFs directly via SSE."""
    pdf_path = INVOICES_DIR / filename
    if not pdf_path.exists() or not filename.endswith(".pdf"):
        raise HTTPException(status_code=404, detail="Sample invoice not found")
    file_bytes = pdf_path.read_bytes()
    return StreamingResponse(
        run_pipeline(file_bytes, filename),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "X-Accel-Buffering": "no",
        },
    )


@app.post("/api/run")
async def start_run(file: UploadFile = File(...)):
    """Accept a PDF, stream pipeline events as Server-Sent Events."""
    if not file.filename.lower().endswith(".pdf"):
        raise HTTPException(status_code=400, detail="Only PDF files are accepted")

    file_bytes = await file.read()
    if len(file_bytes) > 20 * 1024 * 1024:  # 20MB limit
        raise HTTPException(status_code=400, detail="File too large (max 20MB)")

    return StreamingResponse(
        run_pipeline(file_bytes, file.filename),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "X-Accel-Buffering": "no",   # Disable nginx buffering
        },
    )


@app.get("/api/runs")
async def list_runs(limit: int = 50):
    return get_runs(limit)


@app.get("/api/runs/{run_id}")
async def get_run_detail(run_id: str):
    run = get_run(run_id)
    if not run:
        raise HTTPException(status_code=404, detail="Run not found")
    events = get_run_events(run_id)
    # Parse payload_json for each event
    for ev in events:
        try:
            ev["payload"] = json.loads(ev.get("payload_json") or "{}")
        except Exception:
            ev["payload"] = {}
    return {"run": run, "events": events}


class OverrideRequest(BaseModel):
    reviewer: str
    new_decision: str
    note: str = ""


@app.post("/api/runs/{run_id}/override")
async def override_run(run_id: str, body: OverrideRequest):
    run = get_run(run_id)
    if not run:
        raise HTTPException(status_code=404, detail="Run not found")
    valid = {"AUTO_APPROVE", "NEEDS_REVIEW", "REJECT"}
    if body.new_decision not in valid:
        raise HTTPException(status_code=400, detail=f"new_decision must be one of {valid}")
    insert_override(run_id, body.reviewer, run["decision"], body.new_decision, body.note)
    return {"ok": True, "run_id": run_id, "new_decision": body.new_decision}


@app.get("/api/invoices/{filename}")
async def get_invoice_pdf(filename: str):
    """Serve invoice PDF directly for inline preview in the browser."""
    pdf_path = INVOICES_DIR / filename
    if not pdf_path.exists() or not filename.endswith(".pdf"):
        raise HTTPException(status_code=404, detail="PDF not found")
    return FileResponse(pdf_path, media_type="application/pdf")


@app.get("/api/runs/{run_id}/export")
async def export_audit_memo(run_id: str):
    """Export complete auditable memo with all stage events and reasons."""
    run = get_run(run_id)
    if not run:
        raise HTTPException(status_code=404, detail="Run not found")
    events = get_run_events(run_id)
    for ev in events:
        try:
            ev["payload"] = json.loads(ev.get("payload_json") or "{}")
        except Exception:
            ev["payload"] = {}
    return {
        "export_type": "AP_DECISION_AUDIT_MEMO",
        "run": run,
        "events": events,
    }


@app.post("/api/reset-db")
async def reset_database():
    """Reset and re-seed the SQLite database."""
    seed()
    return {"ok": True, "message": "Database re-seeded successfully"}


@app.get("/api/policies")
async def get_policies():
    """Return active mutable enterprise finance policy rulesets."""
    if not POLICIES_PATH.exists():
        return {"policies": []}
    return json.loads(POLICIES_PATH.read_text(encoding="utf-8"))


@app.post("/api/policies")
async def update_policies(body: dict):
    """Mutate enterprise finance policy rulesets dynamically."""
    POLICIES_PATH.write_text(json.dumps(body, indent=2), encoding="utf-8")
    return {"ok": True, "message": "Policies updated successfully"}


# ── RAG Dynamic Knowledge Base routes ─────────────────────────────────────────

class RagSearchRequest(BaseModel):
    query: str
    top_k: int = 3
    vendor: str | None = None


@app.get("/api/rag/rules")
async def get_rag_rules():
    """List all dynamic clauses & contract riders in the RAG vector store."""
    from app.rag_engine import load_knowledge_base
    return {"rules": load_knowledge_base()}


@app.post("/api/rag/rules")
async def save_rag_rule(body: dict):
    """Add or update a dynamic policy clause or vendor rider."""
    from app.rag_engine import add_or_update_rule
    updated = add_or_update_rule(body)
    return {"ok": True, "rule": updated}


@app.delete("/api/rag/rules/{rule_id}")
async def remove_rag_rule(rule_id: str):
    """Delete a dynamic policy clause by ID."""
    from app.rag_engine import delete_rule
    deleted = delete_rule(rule_id)
    if not deleted:
        raise HTTPException(status_code=404, detail="Rule ID not found")
    return {"ok": True, "message": f"Rule {rule_id} deleted"}


@app.post("/api/rag/search")
async def search_rag(body: RagSearchRequest):
    """Semantic vector search over active finance policies and vendor riders."""
    from app.rag_engine import search_rules
    results = search_rules(query=body.query, top_k=body.top_k, vendor=body.vendor)
    return {"results": results, "count": len(results)}


if __name__ == "__main__":
    import uvicorn
    uvicorn.run("app.main:app", host="0.0.0.0", port=8000, reload=True)
