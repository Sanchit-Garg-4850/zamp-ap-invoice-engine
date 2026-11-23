"""
stages/extract.py — Stage 2: Extraction
Strategy (per Master_LLM.md D3):
  1. pdfplumber for text layer
  2. pytesseract OCR if scanned
  3. LLM to fill any missing critical fields
  4. Tag every field with provenance: regex | table | ocr | llm | llm_fallback
"""

import io
import re
import time
import logging
from typing import Optional

import pdfplumber

from app.llm import extract_fields as llm_extract

logger = logging.getLogger(__name__)

CRITICAL_FIELDS = ["invoice_number", "invoice_date", "total", "vendor_name"]


# ── pdfplumber extraction ─────────────────────────────────────────────────────

def _extract_text_pdfplumber(file_bytes: bytes) -> str:
    """Extract all text from a digital PDF."""
    text_parts = []
    with pdfplumber.open(io.BytesIO(file_bytes)) as pdf:
        for page in pdf.pages:
            t = page.extract_text() or ""
            text_parts.append(t)
            # Also try table extraction and append as text
            tables = page.extract_tables() or []
            for table in tables:
                for row in table:
                    if row:
                        text_parts.append(" | ".join(str(c or "") for c in row))
    return "\n".join(text_parts)


# ── OCR extraction ─────────────────────────────────────────────────────────────

def _extract_text_ocr(file_bytes: bytes) -> str:
    """Rasterise PDF pages and run OCR (via pytesseract or direct tesseract CLI)."""
    texts = []
    try:
        import subprocess
        import pymupdf as fitz
        from PIL import Image

        doc = fitz.open(stream=file_bytes, filetype="pdf")
        for page in doc:
            mat = fitz.Matrix(2.0, 2.0)
            pix = page.get_pixmap(matrix=mat)
            png_bytes = pix.tobytes(output="png")

            # Try pytesseract first
            try:
                import pytesseract
                img = Image.open(io.BytesIO(png_bytes))
                t = pytesseract.image_to_string(img)
                if t and t.strip():
                    texts.append(t)
                    continue
            except Exception as pe:
                logger.debug("[extract] pytesseract error (%s), trying CLI", pe)

            # Fallback: direct tesseract CLI via stdin/stdout
            try:
                proc = subprocess.run(
                    ["tesseract", "stdin", "stdout", "--psm", "3"],
                    input=png_bytes,
                    capture_output=True,
                    timeout=15,
                )
                if proc.returncode == 0:
                    text_out = proc.stdout.decode("utf-8", errors="replace")
                    texts.append(text_out)
            except Exception as ce:
                logger.error("[extract] tesseract CLI failed: %s", ce)

        return "\n".join(texts)
    except Exception as e:
        logger.error("[extract] OCR failed: %s", e)
        return ""


# ── Regex helpers ─────────────────────────────────────────────────────────────

def _regex_extract(text: str) -> dict:
    """Fast regex pass. Populates what it can; leaves others None."""

    def find(pattern, text=text, default=None, group=1):
        m = re.search(pattern, text, re.IGNORECASE | re.MULTILINE)
        return m.group(group).strip() if m else default

    def find_float(pattern, text=text, default=None):
        m = re.search(pattern, text, re.IGNORECASE | re.MULTILINE)
        if m:
            try:
                raw = m.group(1).replace(",", "").replace("$", "").replace("£", "").replace("€", "").strip()
                return float(raw)
            except ValueError:
                pass
        return default

    # Date — try multiple formats and normalise to YYYY-MM-DD
    date_val = None
    date_patterns = [
        r"(?:invoice\s*)?date\s*[:\-]?\s*(\d{4}[-/]\d{2}[-/]\d{2})",
        r"(?:invoice\s*)?date\s*[:\-]?\s*(\d{2}[-/]\d{2}[-/]\d{4})",
        r"(?:invoice\s*)?date\s*[:\-]?\s*(\d{1,2}\s+\w+\s+\d{4})",
    ]
    for pat in date_patterns:
        m = re.search(pat, text, re.IGNORECASE)
        if m:
            date_val = _normalise_date(m.group(1).strip())
            if date_val:
                break

    # PO reference — explicit PO-XXXX style pattern only, avoid picking up freetext "reference"
    po_ref = find(r"(?:p\.?o\.?|purchase\s+order)\s*(?:no\.?|number|#|ref(?:erence)?)?\s*[:\-]?\s*(PO[-\s]?\d{4}[-\s]\d{3,6})")
    if not po_ref:
        # Broader match but requiring a code-like token (letters+digits+hyphens, min 5 chars, starts with letter)
        po_ref = find(r"(?:p\.?o\.?|purchase\s+order)\s*(?:no\.?|number|#)?\s*[:\-]?\s*([A-Z]{1,4}[-\s]?\d{4}[-\s]?\d{2,6})")

    # Invoice number — must look like a code, not freetext
    inv_no = find(r"invoice\s*(?:no\.?|number|#)\s*[:\-]?\s*([A-Z]{2,6}[-][A-Z0-9]{2,8}[-]\d{4}[-]\d{2,8})")
    if not inv_no:
        inv_no = find(r"invoice\s*(?:no\.?|number|#)\s*[:\-]?\s*([A-Z0-9][-A-Z0-9]{3,25})")

    # Vendor name — look for lines AFTER a vendor/supplier/from label, NOT "BILL TO"
    vendor_name = None
    vendor_patterns = [
        r"(?:^|\n)(?:vendor|supplier|from|sold\s+by|remit\s+to)\s*[:\-]?\s*([^\n]{3,80})",
    ]
    for pat in vendor_patterns:
        m = re.search(pat, text, re.IGNORECASE | re.MULTILINE)
        if m:
            candidate = m.group(1).strip()
            # Reject generic labels
            if candidate.upper() not in ("BILL TO", "INVOICE", "DATE", "VENDOR", "SUPPLIER"):
                vendor_name = candidate
                break

    # Total — look for grand total / total due first, then plain total
    # Avoid picking up line item amounts
    total = find_float(r"(?:grand\s+)?total\s+due\s*[:\-]?\s*[\$£€₹]?\s*([\d,]+\.?\d*)")
    if total is None:
        total = find_float(r"^total\s*[:\-]?\s*[\$£€₹]?\s*([\d,]+\.?\d*)", text=text)
    if total is None:
        # Last resort: last dollar amount that looks like a total (usually largest on page)
        total = find_float(r"TOTAL\s+DUE[:\s]*[\$£€]?\s*([\d,]+\.?\d*)")

    # Subtotal
    subtotal = find_float(r"sub[-\s]?total\s*[:\-]?\s*[\$£€₹]?\s*([\d,]+\.?\d*)")

    # Tax
    tax_amount  = find_float(r"(?:tax|vat|gst|hst)\s*(?:\(?[\d.]+\s*%\)?)?\s*[:\-]?\s*[\$£€₹]?\s*([\d,]+\.?\d*)")
    tax_rate    = find_float(r"(?:tax|vat|gst)\s*\(?([\d.]+)\s*%\)?")

    # Payment terms
    terms = find(r"(?:payment\s+)?terms?\s*[:\-]?\s*(Net\s*\d+|Due\s+on\s+receipt|Net\s+\w+)")

    return {
        "invoice_number": inv_no,
        "invoice_date":   date_val,
        "vendor_name":    vendor_name,   # Likely None; LLM will fill this
        "bill_to":        find(r"bill\s*to\s*[:\-]?\s*([A-Z][^\n]{3,80})"),
        "po_reference":   po_ref,
        "currency":       find(r"\b(USD|EUR|GBP|INR|AUD|CAD|SGD)\b"),
        "subtotal":       subtotal,
        "tax_amount":     tax_amount,
        "tax_rate_pct":   tax_rate,
        "total":          total,
        "payment_terms":  terms,
        "line_items":     [],  # Regex can't reliably parse tables; LLM handles this
    }


def _normalise_date(raw: str) -> Optional[str]:
    """Try to normalise various date formats to YYYY-MM-DD."""
    from datetime import datetime
    formats = [
        "%Y-%m-%d", "%Y/%m/%d",
        "%d-%m-%Y", "%d/%m/%Y",
        "%d %B %Y", "%d %b %Y",
        "%B %d, %Y", "%b %d, %Y",
    ]
    for fmt in formats:
        try:
            return datetime.strptime(raw, fmt).strftime("%Y-%m-%d")
        except ValueError:
            continue
    return raw  # Return as-is if we can't normalise


# ── Merge + provenance ────────────────────────────────────────────────────────

def _merge(regex_data: dict, llm_data: dict, llm_source: str) -> tuple[dict, dict]:
    """
    Merge regex and LLM results.
    Returns (merged_fields, provenance_map).
    """
    merged = {}
    provenance = {}

    all_keys = set(list(regex_data.keys()) + list(llm_data.keys()))

    for key in all_keys:
        r_val = regex_data.get(key)
        l_val = llm_data.get(key)

        if r_val is not None and l_val is not None:
            # Both found — prefer LLM for text fields, regex for numbers (more accurate)
            if isinstance(r_val, (int, float)):
                merged[key] = r_val
                provenance[key] = "regex+llm_agree" if abs(float(r_val) - float(l_val or 0)) < 0.01 else "regex_preferred"
            else:
                merged[key] = l_val
                provenance[key] = llm_source
        elif r_val is not None:
            merged[key] = r_val
            provenance[key] = "regex"
        elif l_val is not None:
            merged[key] = l_val
            provenance[key] = llm_source
        else:
            merged[key] = None
            provenance[key] = "none"

    return merged, provenance


def _missing_critical(fields: dict) -> list[str]:
    return [f for f in CRITICAL_FIELDS if not fields.get(f)]


# ── Main stage entry point ────────────────────────────────────────────────────

def run(file_bytes: bytes, file_hash: str, pdf_type: str) -> dict:
    """
    Returns stage event payload with extracted fields and provenance.
    """
    t0 = time.time()

    raw_text = ""
    text_source = "pdfplumber"

    if pdf_type == "digital":
        raw_text = _extract_text_pdfplumber(file_bytes)
        if len(raw_text.strip()) < 50:
            # Fallback to OCR even for "digital" (sometimes embedded images)
            logger.info("[extract] digital PDF had too little text, trying OCR")
            raw_text = _extract_text_ocr(file_bytes)
            text_source = "ocr_fallback"
    else:
        raw_text = _extract_text_ocr(file_bytes)
        text_source = "ocr"

    # Pass 1: regex
    regex_fields = _regex_extract(raw_text)
    missing = _missing_critical(regex_fields)

    # Pass 2: LLM — only if critical fields are missing, vendor_name is missing, or file is scanned
    llm_fields = {}
    llm_source = "none"
    if missing or pdf_type == "scanned" or not regex_fields.get("vendor_name"):
        logger.info("[extract] LLM pass triggered (missing: %s, type: %s)", missing, pdf_type)
        llm_fields, llm_source = llm_extract(raw_text, file_hash)

    # Merge
    if llm_fields:
        merged_fields, provenance = _merge(regex_fields, llm_fields, llm_source)
    else:
        merged_fields = {**regex_fields}
        provenance = {k: ("regex" if v is not None else "none") for k, v in regex_fields.items()}

    # Compute confidence
    critical_found = [f for f in CRITICAL_FIELDS if merged_fields.get(f)]
    confidence = len(critical_found) / len(CRITICAL_FIELDS)

    duration_ms = int((time.time() - t0) * 1000)

    return {
        "stage": "extract",
        "status": "ok" if confidence >= 0.75 else "warn",
        "duration_ms": duration_ms,
        "text_source": text_source,
        "llm_source": llm_source,
        "raw_text": raw_text,
        "raw_text_length": len(raw_text),
        "fields": merged_fields,
        "provenance": provenance,
        "missing_critical": _missing_critical(merged_fields),
        "confidence": round(confidence, 2),
    }
