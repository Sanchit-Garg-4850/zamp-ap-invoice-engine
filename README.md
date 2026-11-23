# Zamp AI Solutions Analyst — PS-1 Invoice Processing Engine

Automated, explainable, and audit-ready Accounts Payable pipeline from PDF to decision.

[![Deploy to Render](https://render.com/images/deploy-to-render-button.svg)](https://render.com/deploy?repo=https://github.com/Sanchit-Garg-4850/zamp-ap-invoice-engine)

> **Core Design Principle:**
> *"The LLM reads and formats. Deterministic code decides."*
> Every decision is 100% reproducible, explainable to a non-technical buyer, and tracked in an immutable audit trail.

---

## 🌐 24/7 Cloud Hosting for Recruiters & Evaluators

Deploy this full application with 1 click to Render for permanent 24/7 availability:
1. Fork or open this repository: [https://github.com/Sanchit-Garg-4850/zamp-ap-invoice-engine](https://github.com/Sanchit-Garg-4850/zamp-ap-invoice-engine)
2. In [Render Dashboard](https://dashboard.render.com), click **New +** > **Web Service**.
3. Select `Sanchit-Garg-4850/zamp-ap-invoice-engine`.
4. Render automatically picks up the `Dockerfile` and launches your live URL (e.g. `https://zamp-ap-invoice-engine.onrender.com`).

---

## 🚀 Quickstart (Running Locally)

### 1. Install Dependencies
```bash
pip install -r requirements.txt
```

*(Note: Tesseract OCR is supported out-of-the-box for scanned documents).*

### 2. Seed Database & Generate Test Invoices
```bash
python scripts/seed.py
python scripts/make_invoices.py
```

### 3. Run Pipeline Smoke Test (All 4 Scenarios)
```bash
python scripts/smoke_test.py
```

### 4. Start the Web Server & UI
```bash
uvicorn app.main:app --host 0.0.0.0 --port 8000 --reload
```
Open your browser at:
- **Live Run View:** [http://localhost:8000/](http://localhost:8000/)
- **Dashboard & Audit History:** [http://localhost:8000/dashboard](http://localhost:8000/dashboard)

---

## 🏗️ Architecture & Pipeline Stages

```
                Incoming Vendor Invoice PDF
                            │
                            ▼
┌─────────────────────────────────────────────────────────────┐
│ 1. INGEST           SHA-256 hash, PDF text layer detection │
│ 2. EXTRACT          pdfplumber + Tesseract OCR + LLM fallback│
│ 3. VALIDATE         Arithmetic checks (lines, subtotal, tax)│
│ 4. VENDOR MATCH     rapidfuzz token matching against master │
│ 5. DUPLICATE CHECK  Exact hash, exact inv#, Levenshtein dist│
│ 6. PO MATCH         Explicit lookup & candidate ranking     │
│ 7. TOLERANCE CHECK  Variance check vs PO remaining balance  │
│ 8. DECISION ENGINE  Auditable ladder: REJECT > REVIEW > PASS│
└─────────────────────────────────────────────────────────────┘
                            │
                            ▼
     Live SSE Stream ──► Web UI & Operator Dashboard
```

Each stage emits structured JSON events over **Server-Sent Events (SSE)** in real time.

---

## 🧪 7 Deliberate Edge Cases (1-Click Run in UI)

| # | Scenario | Challenge | Pipeline Behavior | Final Verdict |
|---|---|---|---|---|
| **1** | **Happy Path** (`happy_path.pdf`) | Clean digital PDF, explicit PO reference, exact vendor name, amount within tolerance. | Exact PO match, tolerance variance +0.0%, all arithmetic checks pass. | **AUTO_APPROVE** ✅ |
| **2** | **Split PO** (`split_po.pdf`) | Second invoice against `PO-2024-007` ($20,000 total, $8,000 previously billed). | Evaluates against remaining balance ($12,000) rather than full PO amount. | **AUTO_APPROVE** ✅ |
| **3** | **Near-Duplicate** (`near_duplicate.pdf`) | Same vendor, same amount ($5,750), same date (2024-04-10), invoice number `INV-TP-2202` vs prior `INV-TP-2201`. | Caught by `DUP_002` (Levenshtein distance = 1). Flags potential fraud / double-billing. | **NEEDS_REVIEW** ⚠️ |
| **4** | **Scanned / No PO** (`scanned_no_po.pdf`) | Rasterized image-only PDF with noise, vendor alias ("Global Log Co"), missing PO reference. | Activates OCR fallback, resolves vendor via alias fuzzy match, flags missing PO, auto-drafts vendor email. | **NEEDS_REVIEW** ⚠️ |
| **5** | **Blocked Vendor** (`blocked_vendor.pdf`) | Invoice submitted by "Fraudster Corp", which is flagged as `blocked` in the vendor master. | Stage 4 (Vendor Check) catches `VND_001` (Blocked Vendor status) and halts immediately. | **REJECT** ❌ |
| **6** | **PO Overrun** (`overrun_po.pdf`) | Invoice total $4,500 against PO `PO-2024-005` ($3,200 limit) — a +40.6% price overrun. | Stage 7 (Tolerance) catches `TOL_003` (exceeds upper variance threshold limit). | **REJECT** ❌ |
| **7** | **Unbundled Surcharge (RAG Policy)** (`messy_reconciled.pdf`) | Invoice total $8,450 vs subtotal $8,100 (+$350 discrepancy from unbundled freight in footer text). | RAG Policy Reconciler maps discrepancy to enterprise policy `FIN-POL-01` (Freight Allowance) and verifies allowable adjustment. | **AUTO_APPROVE** ✅ |

*Bonus: Resubmitting any previously approved PDF triggers `DUP_001` (Exact File Hash match) and is instantly **REJECTED** ❌.*

---

## 📜 Enterprise Finance Policy Ruleset (RAG Utility)

Mutable enterprise financial policies are stored in `data/finance_policies.json` and can be inspected via the **📜 Finance Rulesets (RAG)** button in the UI:
* **`FIN-POL-01`**: Standard Logistics & Freight Allowance (up to 12% / $500 max).
* **`FIN-POL-02`**: Fuel Surcharge & Handling Adjustment (up to 10% / $350 max).
* **`FIN-POL-03`**: Early Settlement & Volume Credit (up to 15% / $1,000 max).
* **`FIN-POL-04`**: Compound & Municipal Tax Buffer (up to 1.5% / $50 max).

---

## 📊 Deliverables & Features

1. **Live Run View (`/`)**:
   - Interactive drag-and-drop PDF uploader + 1-click sample invoice buttons.
   - Real-time stage cards lighting up as SSE events arrive (OK / WARN / FAIL / RUNNING).
   - Side panel showing extracted fields with provenance tags (`regex`, `ocr`, `llm`, `cache`).
   - Counterfactual reasoning banner (*"Would auto-approve if total were ≤ $X"*).
   - Auto-generated vendor email draft for missing information with one-click copy.

2. **Operations Dashboard (`/dashboard`)**:
   - Top KPI cards: Total Runs, Auto-Approved, Needs Review, Rejected, Straight-Through Processing %.
   - Filterable runs table with search by invoice #, vendor, or reason code.
   - Interactive modal to inspect full 8-stage audit logs.
   - **Human-in-the-Loop Override:** AP auditors can override decisions with reasons logged into the audit trail.

---

## ⚙️ Configuration & Reason Codes (`app/rules.yaml`)

Thresholds are configurable without touching code and are snapshotted on every run:
- `EXT_001`: Missing critical field (invoice number, date, or total)
- `VAL_001` / `VAL_002`: Line item or tax arithmetic mismatch
- `VND_001` / `VND_002`: Vendor not in master or fuzzy match below threshold
- `DUP_001` / `DUP_002`: Exact or near-duplicate invoice detected
- `PO_001` / `PO_002`: PO missing, not found, or implied match
- `TOL_001` / `TOL_002` / `TOL_003`: Variance tolerance bands (OK, Review, Reject)
