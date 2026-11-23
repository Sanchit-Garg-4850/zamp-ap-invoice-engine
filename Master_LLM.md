# PS-1 Invoice Processing: Full Plan, Architecture Decisions and Trade Offs

Zamp AI Solutions Analyst case study. One day build, CPU only machine, free hosted LLM.
Status: working draft v1, to be critiqued and improved before building.

---

## 1. Summary

**Problem chosen:** PS-1, Invoice processing from PDF to decision.

**What we are building:** A web app that takes a vendor invoice PDF, extracts its fields, validates it against a vendor master, a purchase order (PO) dataset and invoice history, and produces one of three decisions (AUTO APPROVE, NEEDS REVIEW, REJECT) with every step and reason visible.

**Core principle:** The LLM reads and explains. Deterministic code decides. The decision is never made by a model, so every verdict is reproducible and auditable.

**What is graded (from the candidate guide):**
* A process that actually runs end to end on real inputs
* A live run view showing each stage as it executes
* A dashboard showing history, status and outputs across runs
* 2 to 4 deliberate edge cases of our own design
* A 5 minute demo video and a live interview demo
* Ability to explain every design decision to a non technical buyer

---

## 2. Why PS-1

| Option | Fit | Reason |
|---|---|---|
| PS-1 Invoice processing | Best | Matches existing work on messy PDF extraction (Bill of Entry extractor, OCR pipeline), explainable rules and exceptions (SAP GRC SoD pipeline) and anomaly detection (fraud detection project) |
| PS-2 Vendor onboarding | Second | Rule heavy and clean, but less document handling, so it shows less of existing strengths |
| PS-3 Personalised outreach | Weakest | Mostly web research and writing, little overlap with existing strengths |

---

## 3. Constraints and how they shaped the design

| Constraint | Consequence |
|---|---|
| One day instead of one week | Cut anything not visible in the demo. Four edge cases, not ten. Plain HTML UI instead of a React build. No embeddings. |
| No GPU, CPU only | No heavy local models in the critical path. Use a free hosted LLM (Groq), keep local Ollama as an optional fallback only. |
| Cost sensitivity (Claude API too costly) | Free tier hosted model plus heavy use of deterministic code, so LLM calls are few and small. |
| Live and runnable submission link required | Must deploy to a public URL. Hosted LLM makes this possible on a free host. |
| Live demo in the interview | Cache everything by file hash, add a mock provider, rehearse the exact run order. |

---

## 4. Overall architecture

```
Upload PDF (simulates email inbox)
   |
[1 Ingest]       hash file, create run id, detect text layer vs scanned
   |
[2 Extract]      pdfplumber + regex first
   |             fallback: Tesseract OCR, then LLM to schema constrained JSON
   |
[3 Validate]     line items vs subtotal, subtotal + tax vs total, dates, currency, missing fields
   |
[4 Vendor check] fuzzy match against approved vendor master
   |
[5 Duplicate]    file hash, exact vendor + invoice number, near duplicate check
   |
[6 PO match]     explicit PO reference, else ranked candidate match, track remaining balance
   |
[7 Tolerance]    tiered variance rules per vendor
   |
[8 Decision]     reject > review > approve, reason codes, counterfactual
   |
[9 Outputs]      memo, JSON, vendor email draft, audit log
```

Every stage emits one structured event. The UI only renders events. This keeps the backend and the UI loosely coupled and makes each UI piece thin.

---

## 5. Architecture decision log

Each entry lists the options considered, what we chose and the trade off we accept.

### D1. Who makes the decision: LLM or code?
* **Options:** LLM decides end to end, or LLM extracts and code decides.
* **Chosen:** Code decides. LLM only extracts fields and, optionally, phrases text.
* **Why:** Money decisions need to be reproducible and explainable. A rules engine gives the same output every time and can name the exact rule that fired.
* **Trade off:** Less flexible on strange cases. Mitigation: anything uncertain routes to NEEDS REVIEW instead of guessing.

### D2. Which LLM, and where does it run?
* **Options:** Claude API, local Llama or Qwen on CPU through Ollama, free hosted API (Groq).
* **Chosen:** Groq free tier as primary. Ollama optional. A mock provider replays cached results.
* **Why:** Claude API cost is a concern. CPU inference is slow (30 to 90 seconds on a scanned invoice is plausible) and a free web host cannot run Ollama, so the live link would not work. Groq is fast, has a free tier with no credit card required and works from any host.
* **Trade offs accepted:**
  * Free tier rate limits are per organisation and per model and can change without notice. Check the exact numbers in the Groq console.
  * Smaller models make more extraction mistakes. The validation stage is our safety net.
  * Dependency on an external service during the demo. Mitigation: retry with backoff, then cache and mock fallback.
* **Interface:** `extract_llm(text) -> JSON` with `LLM_PROVIDER = groq | ollama | mock`.

### D3. How to extract fields from PDFs
* **Options:** LLM only, regex and table parsing only, hybrid.
* **Chosen:** Hybrid. pdfplumber plus regex first. LLM only when a critical field is missing or the file is scanned.
* **Why:** Cuts LLM calls sharply, is faster, cheaper and more predictable. Also lets us show provenance per field (regex, OCR or LLM).
* **Trade off:** Regex is brittle on unseen layouts. Mitigation: LLM fallback and a clear low confidence path to review.

### D4. Scanned invoices
* **Options:** Vision language model, or OCR plus text LLM.
* **Chosen:** Tesseract OCR, then the text LLM.
* **Why:** Tesseract is light on CPU and reliable. A vision model adds cost, latency and uncertainty.
* **Trade off:** OCR errors on noisy scans. Mitigation: arithmetic validation catches misread numbers.

### D5. Confidence scores
* **Options:** Ask the model for confidence, or derive it from checks.
* **Chosen:** Derive it from checks (did the field pass regex, did totals reconcile, did two extraction paths agree).
* **Why:** Self reported confidence from small models is unreliable.
* **Trade off:** Coarser than a numeric model score. Acceptable.

### D6. PO matching method
* **Options:** Embeddings with ChromaDB, or fuzzy string plus numeric scoring.
* **Chosen:** rapidfuzz plus vendor and amount scoring. No embeddings.
* **Why:** Faster to build in one day, no model download, easy to explain.
* **Trade off:** Matches on totals and vendor mostly, not deep line item semantics. State this honestly as a known limitation and as a next step (embeddings over line item descriptions).

### D7. Decision logic shape
* **Options:** Weighted score, or ordered ladder.
* **Chosen:** Ordered ladder: any hard fail gives REJECT, else any warning gives NEEDS REVIEW, else AUTO APPROVE.
* **Why:** Easy to read, easy to explain to a buyer, easy to show as a trace in the UI.
* **Trade off:** Less nuanced than a score. Acceptable for a demo.

### D8. Explanations
* **Options:** LLM written explanation, or templates keyed by reason code.
* **Chosen:** Templates keyed by reason code, plus a counterfactual line.
* **Why:** Reproducible, no hallucination risk, no extra LLM cost or latency.
* **Trade off:** Less natural prose. Acceptable.

### D9. Backend and streaming
* **Chosen:** FastAPI with Server Sent Events (SSE).
* **Why:** Fast to write, SSE gives the live run view with little code.
* **Trade off:** One way streaming only. Enough for our needs.

### D10. Frontend
* **Options:** React or Next.js, or a single page HTML with vanilla JS or Alpine, served by FastAPI.
* **Chosen:** Plain HTML and JS served by FastAPI.
* **Why:** Saves roughly 1 to 2 hours of build setup in a one day window. The guide says a polished product UI is not required, but a clear live run view and dashboard are.
* **Trade off:** Less polished and less componentised. Acceptable, spend the time on clarity instead.

### D11. Storage
* **Chosen:** SQLite.
* **Why:** Zero setup, a single file, easy to seed from CSV.
* **Trade off:** Not for production scale. Fine for a demo, and Postgres is a next step.

### D12. Deployment
* **Chosen:** Render or Railway free tier, Groq key as an environment variable.
* **Trade off:** Free tiers can cold start slowly. Mitigation: open the app a few minutes before the demo.

### D13. Caching
* **Chosen:** Cache every extraction result by file hash.
* **Why:** Reruns in the demo are instant, and the mock provider can replay them if the LLM is unavailable.

---

## 6. Technology stack

| Layer | Choice |
|---|---|
| Backend | Python, FastAPI, SSE |
| Frontend | HTML, vanilla JS (or Alpine), served by FastAPI |
| Database | SQLite |
| PDF text | pdfplumber |
| OCR | Tesseract through pytesseract |
| Fuzzy matching | rapidfuzz |
| LLM | Groq free tier (small Llama class model for extraction, larger model as retry option), optional Ollama, mock replay |
| Test data | reportlab for PDFs, Pillow for the scanned version |
| Config | rules.yaml for thresholds and reason codes |
| Deploy | Render or Railway free tier |

---

## 7. LLM usage policy

The LLM has exactly one job: turn messy text into a schema constrained JSON object.

1. It is called only if regex extraction leaves a critical field empty, or the file is scanned.
2. Input is page text capped at roughly 1,500 tokens.
3. Output is requested in JSON schema mode if the chosen model supports it. Otherwise use plain JSON mode and validate with pydantic, retrying once.
4. On a validation failure, retry once with the larger model.
5. On a rate limit (429), back off and retry, then fall back to cache, then to mock.
6. Extraction results are cached by file hash.

---

## 8. Data model

| Table | Key fields |
|---|---|
| vendors | id, name, aliases, status (approved or blocked), currency, tolerance_pct |
| pos | po_number, vendor_id, total, currency, status, issued_date |
| po_lines | po_number, description, qty, unit_price |
| invoices_seen | file_hash, vendor_id, invoice_no, total, date, run_id |
| runs | run_id, filename, status, decision, primary_reason, created_at |
| events | run_id, stage, status, payload_json, duration_ms |
| audit | run_id, rules_version, model, config_snapshot, timestamp |
| overrides | run_id, reviewer, new_decision, note |

**Seed data:** about 6 vendors (with aliases), about 10 POs, and a few prior invoices to support duplicate detection and split PO scenarios.

---

## 9. Rules and reason codes

| Code | Check | Result |
|---|---|---|
| EXT_001 | Missing invoice number, date or total | REVIEW, draft vendor email |
| VAL_001 | Line items do not sum to subtotal | REVIEW |
| VAL_002 | Subtotal plus tax differs from total | REVIEW |
| VND_001 | Vendor not in master | REJECT |
| VND_002 | Fuzzy vendor match below threshold | REVIEW |
| DUP_001 | Same file hash, or same vendor plus invoice number | REJECT |
| DUP_002 | Near duplicate: same vendor, amount and date, invoice number within edit distance of 2 | REVIEW, high severity |
| PO_001 | No PO reference and no confident match | REVIEW |
| PO_002 | Implied PO match confidence below threshold | REVIEW |
| TOL_001 | Variance within tolerance against PO remaining balance | PASS |
| TOL_002 | Variance in review band (about 2 to 10 percent) | REVIEW |
| TOL_003 | Variance above the upper band (about 10 percent) | REJECT |

Thresholds live in `rules.yaml`, configurable per vendor, and are snapshotted into the audit log on every run.

**Decision ladder:**
1. Any REJECT result gives REJECT.
2. Else any REVIEW result gives NEEDS REVIEW.
3. Else AUTO APPROVE.

The memo names the deciding rule and adds a counterfactual such as "would auto approve if the total were at or below X".

---

## 10. Making decisions visible (explainability design)

Nothing is a black box. Every stage and every rule writes a structured record, and the UI renders those records directly.

**Stage event schema (example):**
```json
{
  "run_id": "r_104",
  "stage": "tolerance_check",
  "status": "warn",
  "duration_ms": 12,
  "inputs": {"invoice_total": 10450, "po_remaining": 10000},
  "checks": [
    {
      "rule_id": "TOL_002",
      "desc": "Invoice within PO remaining balance",
      "expected": "<= 10000 (+2%)",
      "actual": 10450,
      "variance_pct": 4.5,
      "result": "REVIEW",
      "severity": "medium"
    }
  ]
}
```

**Elements:**
1. **Stage cards:** each stage is an expandable card showing inputs, outputs and every check as expected vs actual with a pass, warn or fail badge.
2. **Decision trace:** a short ladder, for example "Hard fails: none. Warnings: 1 (TOL_002). Result: NEEDS REVIEW."
3. **Field provenance:** every extracted value is tagged with how it was obtained (regex, table, OCR, LLM) and whether it was cross verified.
4. **Counterfactual:** what would change the outcome, so an AP person knows what to do.
5. **Audit log:** append only, with timestamp, rules version, model name and config snapshot, so replaying the same invoice gives the same decision.
6. **Override tracking:** if a reviewer flips a decision, log who and why.

**Outputs per run:** decision memo (templated), raw JSON, vendor email draft when information is missing, audit entry.

**Deferred (nice to have):** highlighting the source location of a field in the PDF viewer using bounding boxes.

---

## 11. Edge cases

| # | Scenario | Expected behaviour |
|---|---|---|
| 1 | **Happy path:** clean text PDF, explicit PO, exact vendor, within tolerance | AUTO APPROVE |
| 2 | **Split PO:** second of several invoices against one PO | Checked against remaining PO balance, not the full PO amount |
| 3 | **Near duplicate:** same vendor, amount and date, invoice number differs by one character | Caught by DUP_002, routed to review as high severity |
| 4 | **Scanned invoice with no PO reference:** OCR, LLM extraction, implied PO match | Match shown with a confidence score, routed to NEEDS REVIEW instead of a guess |
| 5 | **Tax or total mismatch** (first to cut if time is short) | Rules engine names the exact failing check |

Priority: build 1 to 4 well. Case 5 is optional. The guide says a process that handles three scenarios well beats one that half handles ten.

---

## 12. User interface

**Run view**
* Upload box, plus a "load sample" dropdown with the prepared test invoices
* Stage cards filling in live through SSE, with status and timing
* Side panel with extracted fields and provenance tags
* Final verdict banner with the memo and counterfactual

**Dashboard**
* Runs table (status, vendor, amount, primary reason code)
* Filters by decision and reason code
* Counts by decision
* Click a row to reopen its full trace
* Override button that logs reviewer and note

---

## 13. Test data

Generated with scripts so the demo is fully reproducible:
* About 5 invoice PDFs with reportlab, each tied to one scenario
* One scanned style invoice created by rasterising a PDF and adding noise
* Vendor master, PO dataset and invoice history CSVs seeded into SQLite
* Vendor aliases (for example "Acme Pvt Ltd" vs "ACME Private Limited") to exercise fuzzy matching

---

## 14. Repository structure

```
app/
  main.py          FastAPI routes and SSE
  pipeline.py      stage runner and event emitter
  stages/
    ingest.py
    extract.py
    validate.py
    vendor.py
    duplicate.py
    po_match.py
    tolerance.py
    decide.py
  llm.py           provider interface (groq, ollama, mock) and cache
  rules.yaml       thresholds and reason codes
  memo.py          memo and email templates
  db.py
static/
  run.html
  dashboard.html
data/              seed CSVs and sample invoices
scripts/
  make_invoices.py
  seed.py
```

---

## 15. Execution timeline (one day, about 11 to 12 hours)

| Time | Task |
|---|---|
| 0:00 to 0:45 | Repo, schemas, seed data, rules.yaml. Send the "ASA Case Study, [Your Name], PS-1" email. |
| 0:45 to 1:45 | Generate test invoices and the scanned version. Get Groq key, install Tesseract. |
| 1:45 to 3:00 | Stages 1 and 2: ingest and extraction (regex first, OCR and LLM fallback), cache by hash. |
| 3:00 to 4:30 | Stages 3 to 5: validation, vendor check, duplicate detection. |
| 4:30 to 5:45 | Stages 6 to 8: PO match, tolerance, decision ladder, memo templates. |
| 5:45 to 6:30 | **Checkpoint:** happy path works end to end through the API. No UI work before this passes. |
| 6:30 to 7:15 | Extraction hardening (time gained by dropping local model setup): retry logic, larger model retry, low confidence routing. |
| 7:15 to 9:00 | Run view UI with SSE. |
| 9:00 to 10:00 | Dashboard and override. |
| 10:00 to 10:45 | Deploy, test the live link, verify the mock fallback. |
| 10:45 to 11:45 | Rehearse the demo order and record the 5 minute video. |

**Cut order if behind schedule:**
1. Edge case 5 (tax mismatch)
2. Override feature
3. Dashboard filters
4. Memo polish

Never cut: the live run view, the happy path, edge cases 2 to 4, the deployed link.

---

## 16. Risks and mitigations

| # | Risk | Mitigation | Status |
|---|---|---|---|
| 1 | Extraction fails on invoices we did not prepare (interviewer may upload their own) | LLM fallback, validation checks, low confidence routes to review, hardening time in the plan | Open, biggest risk |
| 2 | CPU latency | Hosted Groq model, stage status streamed in the UI | Mostly solved |
| 3 | Too many edge cases for one day | Target four, case 5 is first to cut | Open |
| 4 | Free host cannot run Ollama | Use hosted LLM through an API call | Solved |
| 5 | PO matching uses totals and vendor, not deep line semantics | State as a known limitation, propose embeddings as a next step | Open, accepted |
| 6 | Groq rate limit or outage during the demo | Retry with backoff, then cache, then mock provider | Handled |
| 7 | Free tier terms change without notice | Provider interface lets us switch quickly, check limits in the console before the demo | Monitored |
| 8 | Free host cold start | Open the app minutes before the demo | Handled |

---

## 17. Assumptions to state in the interview

* Currency and tolerance thresholds are configurable per vendor.
* The human review queue is the safe default whenever confidence is low.
* Email intake is simulated with upload, with a clear path to connect an inbox later.
* All test data is synthetic, so no privacy concern arises from calling a hosted LLM.
* Free tier limits for Groq are checked in the console, not assumed.

---

## 18. Demo script (video and live interview)

1. Show the dashboard (empty or seeded history).
2. Run the happy path. Narrate each stage and open one stage card to show expected vs actual.
3. Run the split PO case. Point out the remaining balance logic.
4. Run the near duplicate case. Explain why exact matching would have missed it.
5. Run the scanned invoice with no PO. Show OCR, the LLM step, the match confidence and the route to review.
6. Show the memo, the counterfactual and the vendor email draft.
7. Override one decision and show it in the audit log.
8. Close with limitations and next steps.

**Key talking points:**
* "The model reads, the code decides."
* "I do not trust the model, I verify it" (arithmetic validation and cross checks).
* "Every verdict can be replayed from the audit log."
* "Here is what I would build next."

---

## 19. Known limitations and next steps

* Embedding based PO line item matching
* Bounding box evidence highlighting in a PDF viewer
* Real inbox intake (email integration)
* Postgres and background job queue for volume
* Learning from reviewer overrides to tune thresholds
* A vision model path for hard scans

---

## 20. Open questions for the next critique round

1. Which Groq model exactly, and does it support JSON schema mode on the free tier?
2. How much should we invest in extraction hardening versus the UI?
3. Should we keep four edge cases or reduce to three to protect polish?
4. Is the 2 percent and 10 percent tolerance band reasonable, or should it be tied to PO size?
5. Do we need the vendor email draft for every review case, or only missing information cases?
