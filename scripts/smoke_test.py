"""
scripts/smoke_test.py
Runs all 4 test invoices through the pipeline synchronously (no FastAPI / SSE).
Uses LLM_PROVIDER=mock so no Groq key needed.
Prints a summary table at the end.

Run: python scripts/smoke_test.py
"""

import sys
import os
import asyncio
import json
from pathlib import Path

# Use mock LLM for the smoke test
os.environ["LLM_PROVIDER"] = "mock"

sys.path.insert(0, str(Path(__file__).parent.parent))

from app.db import init_db
from app.pipeline import run_pipeline
from scripts.seed import seed

INVOICES_DIR = Path(__file__).parent.parent / "data" / "invoices"

SCENARIOS = [
    ("happy_path.pdf",    "AUTO_APPROVE"),
    ("split_po.pdf",      "AUTO_APPROVE"),   # second invoice against partially consumed PO
    ("near_duplicate.pdf","NEEDS_REVIEW"),   # DUP_002 near-dup
    ("scanned_no_po.pdf", "NEEDS_REVIEW"),   # no PO ref → implied match attempt
    ("blocked_vendor.pdf","REJECT"),         # VND_001 blocked vendor check
    ("overrun_po.pdf",    "REJECT"),         # TOL_003 amount exceeds upper variance limit
    ("messy_reconciled.pdf","AUTO_APPROVE"), # VAL_003 Finance Policy RAG Reconciled
]


async def run_one(filename: str) -> dict:
    path = INVOICES_DIR / filename
    file_bytes = path.read_bytes()

    final_event = {}
    stage_events = []

    async for sse_line in run_pipeline(file_bytes, filename):
        # Parse SSE lines
        for line in sse_line.strip().split("\n"):
            if line.startswith("data:"):
                try:
                    data = json.loads(line[5:].strip())
                    event_type = None
                    # We'll get the event type from the previous line
                    stage_events.append(data)
                    if "decision" in data and "decision_label" in data:
                        final_event = data
                except json.JSONDecodeError:
                    pass
            elif line.startswith("event:"):
                current_event_type = line[6:].strip()

    return final_event


async def main():
    seed()
    print("\n" + "="*70)
    print("  INVOICE PROCESSOR — PIPELINE SMOKE TEST")
    print("  LLM Provider: mock")
    print("="*70)

    results = []
    for filename, expected in SCENARIOS:
        print(f"\n▶ Running: {filename}")
        print(f"  Expected: {expected}")

        try:
            result = await run_one(filename)
            actual = result.get("decision", "ERROR")
            ok = "✅" if actual == expected else "⚠️ "
            print(f"  Got:      {actual}  {ok}")
            print(f"  Reason:   {result.get('primary_reason', 'n/a')}")
            if result.get("counterfactual"):
                print(f"  Counter:  {result['counterfactual']}")
            results.append((filename, expected, actual, ok))
        except Exception as e:
            print(f"  ERROR: {e}")
            import traceback
            traceback.print_exc()
            results.append((filename, expected, "ERROR", "❌"))

    # Summary table
    print("\n" + "="*70)
    print("  SUMMARY")
    print("="*70)
    print(f"  {'File':<35} {'Expected':<16} {'Got':<16} {'OK'}")
    print(f"  {'-'*35} {'-'*16} {'-'*16} {'-'*4}")
    for fname, exp, got, ok in results:
        print(f"  {fname:<35} {exp:<16} {got:<16} {ok}")
    passed = sum(1 for _, e, g, _ in results if e == g)
    print(f"\n  {passed}/{len(results)} scenarios matched expected decision\n")


if __name__ == "__main__":
    asyncio.run(main())
