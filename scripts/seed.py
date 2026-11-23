"""
scripts/seed.py — Seed the SQLite database with vendors, POs and prior invoices.
Run once: python scripts/seed.py
"""
import sys
import json
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from app.db import init_db, get_conn

VENDORS = [
    # (name, aliases_json, status, currency, tolerance_pct)
    ("Acme Supplies Ltd",        '["ACME Supplies", "Acme Pvt Ltd", "ACME SUPPLIES LTD"]', "approved", "USD", 2.0),
    ("TechParts International",  '["Tech Parts Intl", "TechParts", "TECHPARTS INTERNATIONAL"]', "approved", "USD", 3.0),
    ("Global Logistics Co",      '["Global Logistics", "GLC", "Global Log Co"]', "approved", "USD", 2.0),
    ("OfficeWorld Inc",          '["Office World", "OfficeWorld"]', "approved", "USD", 5.0),
    ("BuildMat Supplies",        '["BuildMat", "Build Mat Supplies", "BuildMat Supply"]', "approved", "USD", 2.0),
    ("Fraudster Corp",           '[]', "blocked", "USD", 0.0),
]

POS = [
    # (po_number, vendor_name, total, currency, status, issued_date, description)
    ("PO-2024-001", "Acme Supplies Ltd",       10000.00, "USD", "open", "2024-01-15", "Office supplies Q1"),
    ("PO-2024-002", "Acme Supplies Ltd",        5000.00, "USD", "open", "2024-02-01", "Cleaning supplies"),
    ("PO-2024-003", "TechParts International", 25000.00, "USD", "open", "2024-01-20", "Server components"),
    ("PO-2024-004", "Global Logistics Co",      8500.00, "USD", "open", "2024-02-10", "Freight services Q1"),
    ("PO-2024-005", "OfficeWorld Inc",          3200.00, "USD", "open", "2024-02-15", "Stationery and paper"),
    ("PO-2024-006", "BuildMat Supplies",       15000.00, "USD", "open", "2024-03-01", "Construction materials"),
    # Partially consumed PO (for split-PO edge case)
    ("PO-2024-007", "Acme Supplies Ltd",       20000.00, "USD", "open", "2024-03-05", "Janitorial supplies annual"),
]

PO_LINES = {
    "PO-2024-001": [
        ("Printer paper (case)", 50, 15.00),
        ("Pens (box)",           20, 8.00),
        ("Staples (box)",        30, 5.00),
        ("Notebooks",            40, 7.50),
        ("Folders",              50, 4.00),
        ("Tape",                 60, 3.00),
    ],
    "PO-2024-003": [
        ("SSD 1TB",    10, 120.00),
        ("RAM 32GB",   20, 180.00),
        ("CPU cooler", 10, 85.00),
        ("PSU 650W",    5, 95.00),
    ],
    "PO-2024-007": [
        ("Floor cleaner (gallon)", 100, 12.00),
        ("Mop heads",              50,  8.00),
        ("Trash bags (box)",       80,  5.00),
        ("Paper towels (case)",    60, 15.00),
    ],
}

# Prior invoice for PO-2024-007 — simulates first invoice of a split PO
# This means the remaining balance is 20000 - 8000 = 12000
PRIOR_INVOICES = [
    # (file_hash, vendor_name, invoice_no, total, invoice_date)
    ("aabbcc001122deadbeef00000000000000000001", "Acme Supplies Ltd", "INV-7001", 8000.00, "2024-03-15"),
]

# Near-duplicate pair — for edge case 3
# We'll add a prior invoice that the near-duplicate test invoice matches against
NEAR_DUP_INVOICE = {
    "file_hash":    "neardup0000000000000000000000000001",
    "vendor_name":  "TechParts International",
    "invoice_no":   "INV-TP-2201",
    "total":        5750.00,
    "invoice_date": "2024-04-10",
}


def seed():
    init_db()
    conn = get_conn()
    cur = conn.cursor()

    # Clear child tables first to respect foreign keys
    cur.execute("DELETE FROM overrides")
    cur.execute("DELETE FROM audit")
    cur.execute("DELETE FROM events")
    cur.execute("DELETE FROM invoices_seen")
    cur.execute("DELETE FROM runs")
    cur.execute("DELETE FROM po_lines")
    cur.execute("DELETE FROM pos")
    cur.execute("DELETE FROM vendors")

    # Vendors
    vendor_name_to_id = {}
    for name, aliases, status, currency, tol in VENDORS:
        cur.execute(
            "INSERT INTO vendors (name, aliases, status, currency, tolerance_pct) VALUES (?,?,?,?,?)",
            (name, aliases, status, currency, tol),
        )
        vendor_name_to_id[name] = cur.lastrowid
    print(f"[seed] {len(VENDORS)} vendors inserted")

    # POs
    for po_number, vendor_name, total, currency, status, issued_date, desc in POS:
        vid = vendor_name_to_id[vendor_name]
        cur.execute(
            "INSERT INTO pos (po_number, vendor_id, total, currency, status, issued_date, description) VALUES (?,?,?,?,?,?,?)",
            (po_number, vid, total, currency, status, issued_date, desc),
        )
    print(f"[seed] {len(POS)} POs inserted")

    # PO lines
    for po_number, lines in PO_LINES.items():
        for desc, qty, unit_price in lines:
            cur.execute(
                "INSERT INTO po_lines (po_number, description, qty, unit_price) VALUES (?,?,?,?)",
                (po_number, desc, qty, unit_price),
            )
    print(f"[seed] PO lines inserted")

    # Prior invoices (for split-PO and near-dup scenarios)
    cur.execute("DELETE FROM invoices_seen")
    cur.execute("DELETE FROM runs")
    cur.execute("DELETE FROM events")

    # Create dummy runs for prior invoices
    for i, (fhash, vendor_name, inv_no, total, inv_date) in enumerate(PRIOR_INVOICES):
        prior_run_id = f"r_prior_{i+1:03d}"
        vid = vendor_name_to_id[vendor_name]
        cur.execute(
            "INSERT INTO runs (run_id, filename, status, decision, primary_reason) VALUES (?,?,?,?,?)",
            (prior_run_id, f"prior_invoice_{i+1}.pdf", "done", "AUTO_APPROVE", "ALL_PASS"),
        )
        cur.execute(
            "INSERT INTO invoices_seen (file_hash, vendor_id, invoice_no, total, invoice_date, run_id) VALUES (?,?,?,?,?,?)",
            (fhash, vid, inv_no, total, inv_date, prior_run_id),
        )
        # Also insert a po_match event so remaining balance lookup works
        import json as _json
        cur.execute(
            "INSERT INTO events (run_id, stage, status, payload_json) VALUES (?,?,?,?)",
            (prior_run_id, "po_match", "ok", _json.dumps({"matched_po": "PO-2024-007"})),
        )

    # Near-duplicate prior invoice
    nd = NEAR_DUP_INVOICE
    nd_run_id = "r_prior_nd_001"
    vid = vendor_name_to_id[nd["vendor_name"]]
    cur.execute(
        "INSERT INTO runs (run_id, filename, status, decision, primary_reason) VALUES (?,?,?,?,?)",
        (nd_run_id, "prior_tp_invoice.pdf", "done", "AUTO_APPROVE", "ALL_PASS"),
    )
    cur.execute(
        "INSERT INTO invoices_seen (file_hash, vendor_id, invoice_no, total, invoice_date, run_id) VALUES (?,?,?,?,?,?)",
        (nd["file_hash"], vid, nd["invoice_no"], nd["total"], nd["invoice_date"], nd_run_id),
    )
    print(f"[seed] Prior invoices and near-dup seed inserted")

    conn.commit()
    conn.close()
    print("[seed] ✅ Done. Database is ready.")


if __name__ == "__main__":
    seed()
