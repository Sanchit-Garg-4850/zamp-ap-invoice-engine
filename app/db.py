"""
db.py — SQLite setup, schema creation and seed helpers.
All tables mirror the data model in Master_LLM.md section 8.
"""
import sqlite3
import json
import os
from pathlib import Path

DB_PATH = Path(__file__).parent.parent / "data" / "invoice_processor.db"


def get_conn() -> sqlite3.Connection:
    conn = sqlite3.connect(str(DB_PATH), check_same_thread=False)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA foreign_keys=ON")
    return conn


def init_db():
    """Create all tables if they do not exist."""
    conn = get_conn()
    cur = conn.cursor()

    cur.executescript("""
    CREATE TABLE IF NOT EXISTS vendors (
        id              INTEGER PRIMARY KEY AUTOINCREMENT,
        name            TEXT NOT NULL,
        aliases         TEXT,          -- JSON array of alias strings
        status          TEXT NOT NULL DEFAULT 'approved',  -- approved | blocked
        currency        TEXT NOT NULL DEFAULT 'USD',
        tolerance_pct   REAL NOT NULL DEFAULT 2.0
    );

    CREATE TABLE IF NOT EXISTS pos (
        po_number       TEXT PRIMARY KEY,
        vendor_id       INTEGER NOT NULL REFERENCES vendors(id),
        total           REAL NOT NULL,
        currency        TEXT NOT NULL DEFAULT 'USD',
        status          TEXT NOT NULL DEFAULT 'open',      -- open | closed | cancelled
        issued_date     TEXT NOT NULL,
        description     TEXT
    );

    CREATE TABLE IF NOT EXISTS po_lines (
        id              INTEGER PRIMARY KEY AUTOINCREMENT,
        po_number       TEXT NOT NULL REFERENCES pos(po_number),
        description     TEXT NOT NULL,
        qty             REAL NOT NULL DEFAULT 1,
        unit_price      REAL NOT NULL
    );

    CREATE TABLE IF NOT EXISTS invoices_seen (
        id              INTEGER PRIMARY KEY AUTOINCREMENT,
        file_hash       TEXT NOT NULL,
        vendor_id       INTEGER REFERENCES vendors(id),
        invoice_no      TEXT,
        total           REAL,
        invoice_date    TEXT,
        run_id          TEXT NOT NULL,
        created_at      TEXT NOT NULL DEFAULT (datetime('now'))
    );

    CREATE TABLE IF NOT EXISTS runs (
        run_id          TEXT PRIMARY KEY,
        filename        TEXT NOT NULL,
        status          TEXT NOT NULL DEFAULT 'running',  -- running | done | error
        decision        TEXT,                             -- AUTO_APPROVE | NEEDS_REVIEW | REJECT
        primary_reason  TEXT,
        created_at      TEXT NOT NULL DEFAULT (datetime('now')),
        completed_at    TEXT
    );

    CREATE TABLE IF NOT EXISTS events (
        id              INTEGER PRIMARY KEY AUTOINCREMENT,
        run_id          TEXT NOT NULL REFERENCES runs(run_id),
        stage           TEXT NOT NULL,
        status          TEXT NOT NULL,  -- ok | warn | fail | running
        payload_json    TEXT,
        duration_ms     INTEGER,
        created_at      TEXT NOT NULL DEFAULT (datetime('now'))
    );

    CREATE TABLE IF NOT EXISTS audit (
        id              INTEGER PRIMARY KEY AUTOINCREMENT,
        run_id          TEXT NOT NULL REFERENCES runs(run_id),
        rules_version   TEXT NOT NULL,
        model           TEXT NOT NULL,
        config_snapshot TEXT,          -- JSON snapshot of rules.yaml
        timestamp       TEXT NOT NULL DEFAULT (datetime('now'))
    );

    CREATE TABLE IF NOT EXISTS overrides (
        id              INTEGER PRIMARY KEY AUTOINCREMENT,
        run_id          TEXT NOT NULL REFERENCES runs(run_id),
        reviewer        TEXT NOT NULL,
        old_decision    TEXT,
        new_decision    TEXT NOT NULL,
        note            TEXT,
        created_at      TEXT NOT NULL DEFAULT (datetime('now'))
    );
    """)

    conn.commit()
    conn.close()
    print(f"[db] schema ready at {DB_PATH}")


# ── Helper functions ──────────────────────────────────────────────────────────

def insert_run(run_id: str, filename: str) -> None:
    conn = get_conn()
    conn.execute(
        "INSERT OR IGNORE INTO runs (run_id, filename, status) VALUES (?,?,?)",
        (run_id, filename, "running"),
    )
    conn.commit()
    conn.close()


def update_run(run_id: str, status: str, decision: str = None, primary_reason: str = None) -> None:
    conn = get_conn()
    conn.execute(
        """UPDATE runs SET status=?, decision=?, primary_reason=?,
           completed_at=datetime('now') WHERE run_id=?""",
        (status, decision, primary_reason, run_id),
    )
    conn.commit()
    conn.close()


def insert_event(run_id: str, stage: str, status: str, payload: dict, duration_ms: int = 0) -> None:
    conn = get_conn()
    conn.execute(
        "INSERT INTO events (run_id, stage, status, payload_json, duration_ms) VALUES (?,?,?,?,?)",
        (run_id, stage, status, json.dumps(payload), duration_ms),
    )
    conn.commit()
    conn.close()


def insert_audit(run_id: str, model: str, rules_version: str, config_snapshot: dict) -> None:
    conn = get_conn()
    conn.execute(
        "INSERT INTO audit (run_id, model, rules_version, config_snapshot) VALUES (?,?,?,?)",
        (run_id, model, rules_version, json.dumps(config_snapshot)),
    )
    conn.commit()
    conn.close()


def get_runs(limit: int = 50):
    conn = get_conn()
    rows = conn.execute(
        "SELECT * FROM runs ORDER BY created_at DESC LIMIT ?", (limit,)
    ).fetchall()
    conn.close()
    return [dict(r) for r in rows]


def get_run_events(run_id: str):
    conn = get_conn()
    rows = conn.execute(
        "SELECT * FROM events WHERE run_id=? ORDER BY id ASC", (run_id,)
    ).fetchall()
    conn.close()
    return [dict(r) for r in rows]


def get_run(run_id: str):
    conn = get_conn()
    row = conn.execute("SELECT * FROM runs WHERE run_id=?", (run_id,)).fetchone()
    conn.close()
    return dict(row) if row else None


def insert_override(run_id: str, reviewer: str, old_decision: str, new_decision: str, note: str) -> None:
    conn = get_conn()
    # Update the run decision too
    conn.execute("UPDATE runs SET decision=? WHERE run_id=?", (new_decision, run_id))
    conn.execute(
        "INSERT INTO overrides (run_id, reviewer, old_decision, new_decision, note) VALUES (?,?,?,?,?)",
        (run_id, reviewer, old_decision, new_decision, note),
    )
    conn.commit()
    conn.close()


def get_vendor_by_id(vendor_id: int):
    conn = get_conn()
    row = conn.execute("SELECT * FROM vendors WHERE id=?", (vendor_id,)).fetchone()
    conn.close()
    return dict(row) if row else None


def get_all_vendors():
    conn = get_conn()
    rows = conn.execute("SELECT * FROM vendors").fetchall()
    conn.close()
    return [dict(r) for r in rows]


def get_pos_for_vendor(vendor_id: int):
    conn = get_conn()
    rows = conn.execute(
        "SELECT * FROM pos WHERE vendor_id=? AND status='open'", (vendor_id,)
    ).fetchall()
    conn.close()
    return [dict(r) for r in rows]


def get_po(po_number: str):
    conn = get_conn()
    row = conn.execute("SELECT * FROM pos WHERE po_number=?", (po_number,)).fetchone()
    conn.close()
    return dict(row) if row else None


def get_po_lines(po_number: str):
    conn = get_conn()
    rows = conn.execute("SELECT * FROM po_lines WHERE po_number=?", (po_number,)).fetchall()
    conn.close()
    return [dict(r) for r in rows]


def get_invoices_for_po(po_number: str):
    """Return prior invoices that matched this PO (to compute remaining balance)."""
    conn = get_conn()
    # Look up runs that approved against this PO
    rows = conn.execute(
        """SELECT i.total FROM invoices_seen i
           JOIN runs r ON i.run_id = r.run_id
           WHERE r.decision = 'AUTO_APPROVE'
           AND i.run_id IN (
               SELECT e.run_id FROM events e
               WHERE e.stage='po_match'
               AND json_extract(e.payload_json, '$.matched_po') = ?
           )""",
        (po_number,),
    ).fetchall()
    conn.close()
    return [dict(r) for r in rows]


def find_prior_invoice(file_hash: str, vendor_id: int, invoice_no: str, total: float, invoice_date: str):
    """Check for exact and near duplicates."""
    conn = get_conn()

    # Exact: file hash
    exact_hash = conn.execute(
        "SELECT * FROM invoices_seen WHERE file_hash=?", (file_hash,)
    ).fetchone()

    # Exact: vendor + invoice_no
    exact_inv = None
    if invoice_no:
        exact_inv = conn.execute(
            "SELECT * FROM invoices_seen WHERE vendor_id=? AND invoice_no=?",
            (vendor_id, invoice_no),
        ).fetchone()

    # Near: same vendor, same amount, same date, different invoice_no
    near = None
    if invoice_date and total:
        near = conn.execute(
            """SELECT * FROM invoices_seen
               WHERE vendor_id=? AND ABS(total - ?) < 0.01 AND invoice_date=?
               AND (invoice_no != ? OR invoice_no IS NULL)""",
            (vendor_id, total, invoice_date, invoice_no),
        ).fetchone()

    conn.close()
    return (
        dict(exact_hash) if exact_hash else None,
        dict(exact_inv) if exact_inv else None,
        dict(near) if near else None,
    )


def record_invoice_seen(file_hash: str, vendor_id: int, invoice_no: str,
                        total: float, invoice_date: str, run_id: str) -> None:
    conn = get_conn()
    conn.execute(
        """INSERT INTO invoices_seen (file_hash, vendor_id, invoice_no, total, invoice_date, run_id)
           VALUES (?,?,?,?,?,?)""",
        (file_hash, vendor_id, invoice_no, total, invoice_date, run_id),
    )
    conn.commit()
    conn.close()
