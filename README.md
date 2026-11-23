# Autonomous Accounts Payable (AP) Invoice Processing Engine
### Production-Grade AI Pipeline: From Unstructured PDF to Auditable Decision

🌐 **Live 24/7 Deployment:** [https://zamp-ap-invoice-engine.onrender.com/](https://zamp-ap-invoice-engine.onrender.com/)  
📊 **AP Operations Dashboard:** [https://zamp-ap-invoice-engine.onrender.com/dashboard](https://zamp-ap-invoice-engine.onrender.com/dashboard)

[![Deploy to Render](https://render.com/images/deploy-to-render-button.svg)](https://render.com/deploy?repo=https://github.com/Sanchit-Garg-4850/zamp-ap-invoice-engine)
![Python](https://img.shields.io/badge/Python-3.11-blue?logo=python)
![FastAPI](https://img.shields.io/badge/FastAPI-0.110+-green?logo=fastapi)
![Docker](https://img.shields.io/badge/Docker-Ready-blue?logo=docker)
![License](https://img.shields.io/badge/License-MIT-lightgrey)

---

## 🏛️ Core Architectural Principle

> **"The LLM reads and structures unstructured documents. Deterministic code and grounded financial policies decide."**

When automating enterprise Accounts Payable (AP), standard AI implementations frequently fail in two ways:
1. **Unconstrained LLMs:** Allowing a language model to directly "decide" whether to approve a \$50,000 disbursement introduces severe hallucination risks, non-deterministic arithmetic, and compliance failure during financial audits.
2. **Brittle Heuristics:** Relying solely on hardcoded regex or rigid formulas shatters the moment an invoice has a multi-column layout, unbundled freight line, OCR noise, or partial purchase order drawdowns.

This system resolves that dilemma through a **hybrid pipeline**: an LLM cascade extracts semantic fields with verified confidence scores, while a **deterministic 8-stage verification ladder** and a **dynamic vector RAG policy engine** evaluate math, vendor legitimacy, duplicates, and contractual tolerance bands.

---

## 🏗️ System Architecture

```
                    Incoming Vendor Invoice PDF
                                │
                                ▼
┌────────────────────────────────────────────────────────────────────────┐
│ STAGE 1: INGEST & CLASSIFICATION                                       │
│ • Detects digital text layer vs rasterized scan                        │
│ • Computes SHA-256 cryptographic document fingerprint                  │
└───────────────────────────────┬────────────────────────────────────────┘
                                │
                                ▼
┌────────────────────────────────────────────────────────────────────────┐
│ STAGE 2: HYBRID EXTRACTION CASCADE                                     │
│ • High-speed text extraction (pdfplumber)                              │
│ • Optical Character Recognition fallback (Tesseract OCR)               │
│ • Structured JSON extraction with field-level confidence scoring       │
└───────────────────────────────┬────────────────────────────────────────┘
                                │
                                ▼
┌────────────────────────────────────────────────────────────────────────┐
│ STAGE 3: ARITHMETIC & SEMANTIC RAG RECONCILIATION                      │
│ • Strict line items sum verification (Σ items = subtotal)              │
│ • Subtotal + Tax = Total Due balance check                             │
│ • Dynamic RAG Layer reconciles unbundled freight/discounts via policy  │
└───────────────────────────────┬────────────────────────────────────────┘
                                │
                                ▼
┌────────────────────────────────────────────────────────────────────────┐
│ STAGE 4: VENDOR MASTER VALIDATION                                      │
│ • Exact VAT / Tax ID matching                                          │
│ • Fuzzy name reconciliation via RapidFuzz token-set scoring            │
│ • Hard fraud block enforcement (BLOCKED vendor status check)           │
└───────────────────────────────┬────────────────────────────────────────┘
                                │
                                ▼
┌────────────────────────────────────────────────────────────────────────┐
│ STAGE 5: DUPLICATE DETECTION                                           │
│ • Exact document SHA-256 collision check                               │
│ • Database invoice number collision lookup                             │
│ • Levenshtein edit-distance = 1 near-duplicate typo fraud screen       │
└───────────────────────────────┬────────────────────────────────────────┘
                                │
                                ▼
┌────────────────────────────────────────────────────────────────────────┐
│ STAGE 6: PO MATCHING & BALANCE TRACKING                                │
│ • Explicit PO reference extraction and existence check                 │
│ • Implicit vendor open commitment matching                             │
│ • Real-time tracking of PO draw-down balances and partial billings     │
└───────────────────────────────┬────────────────────────────────────────┘
                                │
                                ▼
┌────────────────────────────────────────────────────────────────────────┐
│ STAGE 7: TOLERANCE & VARIANCE EVALUATION                               │
│ • Tiered dollar & percentage tolerance bands:                          │
│   - Under-billing / Exact balance  →  PASS (TOL_001)                   │
│   - Overrun ≤ $100.00              →  AUTO_PASS                        │
│   - Overrun ≤ $500.00 and ≤ 5%     →  AUTO_PASS                        │
│   - Overrun > 10.0% variance       →  HARD REJECT (TOL_003)            │
└───────────────────────────────┬────────────────────────────────────────┘
                                │
                                ▼
┌────────────────────────────────────────────────────────────────────────┐
│ STAGE 8: DECISION ENGINE & EXPLAINABILITY                              │
│ • Priority hierarchy: REJECT > NEEDS_REVIEW > AUTO_APPROVE             │
│ • Standardized AP Reason Codes (e.g., TOL_003, VND_001, DUP_002)       │
│ • Counterfactual explainability ("Would approve if total were ≤ $X")   │
│ • Auto-drafted vendor clarification email for missing data             │
└───────────────────────────────┬────────────────────────────────────────┘
                                │
                                ▼
       Real-Time SSE Stream ──► Live Operator UI & Audit Dashboard
```

---

## 🧠 Dynamic RAG Policy Layer

To handle messy real-world invoices where vendors place freight, fuel surcharges, or early payment deductions in footer notes without itemized lines, the system incorporates a **Dynamic Retrieval-Augmented Generation (RAG) Knowledge Base**:

* **Semantic Vector Retrieval:** Uses TF-IDF cosine similarity search over contractual clauses and finance rules.
* **Vendor-Scoped Boost:** Dynamically prioritizes clauses scoped to specific vendor Master Services Agreements (MSAs).
* **Deterministic Boundary Enforcement:** Retrieved clauses supply authorized dollar and percentage ceilings (e.g., *Max $500.00 / 12%*); deterministic code enforces the ceiling.
* **Zero-Downtime Rule Updates:** Contract amendments and policy riders can be dynamically ingested via REST API (`/api/rag/rules`) or the UI without redeploying code.

---

## 🧪 7 Deliberate Edge Cases & Benchmark Scenarios

The engine includes 7 pre-generated realistic test invoices testable via 1-click in the UI or CLI:

| # | Scenario | Test File | Failure Mode / Challenge | Pipeline Behavior | Verdict | Reason Code |
|---|---|---|---|---|---|---|
| **1** | **Happy Path** | `happy_path.pdf` | None (clean digital PDF) | Exact PO match, arithmetic balances, vendor verified at 100% confidence. | **`AUTO_APPROVE`** | `ALL_PASS` |
| **2** | **Split PO Drawdown** | `split_po.pdf` | Partial billing against blanket PO | Evaluates against remaining balance ($12,000) rather than full PO amount. Recognizes valid partial fulfillment. | **`AUTO_APPROVE`** | `TOL_001` |
| **3** | **Near-Duplicate Fraud** | `near_duplicate.pdf` | Invoice number `INV-2024-001A` vs paid `INV-2024-001` | Levenshtein edit-distance = 1 within 90-day window caught by duplicate screen. Prevents double payment. | **`NEEDS_REVIEW`** | `DUP_002` |
| **4** | **Scanned / Missing PO** | `scanned_no_po.pdf` | Low-DPI scan, OCR noise, missing PO | Triggers Tesseract OCR fallback, matches vendor via fuzzy alias, auto-drafts vendor clarification email. | **`NEEDS_REVIEW`** | `EXT_001` |
| **5** | **Blocked / Fraud Vendor** | `blocked_vendor.pdf` | Invoice from blacklisted entity | Vendor master lookup flags `BLOCKED` status. Pipeline halts immediately to protect company funds. | **`REJECT`** | `VND_001` |
| **6** | **PO Cost Overrun** | `overrun_po.pdf` | Total exceeds PO budget by +40.6% | Exceeds upper variance threshold limit. Explains exact boundary condition required for approval. | **`REJECT`** | `TOL_003` |
| **7** | **Unbundled Surcharge** | `messy_reconciled.pdf` | Subtotal + Tax ≠ Total due to $350 freight note | RAG engine semantically matches clause `FIN-POL-01` (Freight Allowance) and reconciles variance to pass. | **`AUTO_APPROVE`** | `VAL_003` |

---

## 📊 Operations Dashboard & Audit Capabilities

* **Real-Time KPIs:** Live monitoring of Total Processed Volume, Straight-Through Processing (Auto-Approve) Rate, and Exception Review Queues.
* **Human-in-the-Loop Override:** AP specialists can review flagged invoices, inspect side-by-side PDF previews against extracted fields, and apply an audit-logged decision override with mandatory reviewer justification notes.
* **Cryptographic Audit Dossier:** 1-click export of an immutable JSON Audit Memo containing all stage events, execution timings, confidence scores, and rule evaluations.

---

## ⚡ Quickstart

### Option 1: Running Locally (Python 3.11+)

```bash
# 1. Clone repository
git clone https://github.com/Sanchit-Garg-4850/zamp-ap-invoice-engine.git
cd zamp-ap-invoice-engine

# 2. Install dependencies
pip install -r requirements.txt

# 3. Seed database & generate test PDFs
python scripts/seed.py
python scripts/make_invoices.py

# 4. Run automated test suite
python scripts/smoke_test.py

# 5. Start the application
uvicorn app.main:app --host 0.0.0.0 --port 8000 --reload
```
Open **[http://localhost:8000](http://localhost:8000)** for the Live Run View, or **[http://localhost:8000/dashboard](http://localhost:8000/dashboard)** for the Operations Dashboard.

### Option 2: Running with Docker

```bash
docker build -t zamp-invoice-engine .
docker run -p 8000:8000 zamp-invoice-engine
```

---

## 🔌 API Reference

| Endpoint | Method | Description |
|---|---|---|
| `/api/run` | `POST` | Upload PDF invoice; streams 8-stage verification pipeline via Server-Sent Events (SSE). |
| `/api/run-sample/{filename}` | `POST` | Execute one of the 7 prepared benchmark invoices with live SSE streaming. |
| `/api/runs` | `GET` | List historic invoice runs with decision status, primary reasons, and metadata. |
| `/api/runs/{id}` | `GET` | Retrieve complete execution trace and stage event payload for a specific run. |
| `/api/runs/{id}/override` | `POST` | Submit human reviewer override with required justification note. |
| `/api/runs/{id}/export` | `GET` | Export complete auditable JSON memo for ERP integration. |
| `/api/rag/rules` | `GET`, `POST` | Read or dynamically register contractual policy clauses and vendor riders. |
| `/api/rag/search` | `POST` | Perform semantic vector similarity search against active policy clauses. |
| `/api/reset-db` | `POST` | Reset and re-seed the SQLite database to clean benchmark state. |

---

## 🛠️ Technology Stack

* **Backend:** Python 3.11, FastAPI, Uvicorn, SQLite, Pydantic v2
* **Document Processing:** `pdfplumber` (digital extraction), `pytesseract` (OCR), `pymupdf` (rendering), `reportlab` (synthetic generation)
* **NLP & Matching:** `RapidFuzz` (token-set vendor matching), Levenshtein distance (duplicate detection), TF-IDF vector cosine indexing (RAG)
* **LLM Engine:** Groq API (`llama-3.3-70b-versatile` / `llama-3.1-8b-instant`) with deterministic offline mock fallback
* **Frontend:** Vanilla HTML5, CSS3, JavaScript (zero-build architecture, responsive dark theme, SSE streaming)
* **Containerization:** Docker multi-stage build, Render Blueprint (`render.yaml`)

---

## 📄 License

This project is licensed under the MIT License.
