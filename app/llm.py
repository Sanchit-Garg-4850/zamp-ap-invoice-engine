"""
llm.py — LLM provider interface.
Supports: groq | mock
Implements: extract_fields(text) -> dict
Caches results by file hash.
"""

import os
import json
import time
import hashlib
import logging
from pathlib import Path
from typing import Optional

import httpx
import yaml

logger = logging.getLogger(__name__)

# Auto-load .env file if present at project root
ENV_FILE = Path(__file__).parent.parent / ".env"
if ENV_FILE.exists():
    for line in ENV_FILE.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if line and not line.startswith("#") and "=" in line:
            k, v = line.split("=", 1)
            os.environ.setdefault(k.strip(), v.strip().strip('"').strip("'"))

CACHE_DIR = Path(__file__).parent.parent / "data" / "llm_cache"
CACHE_DIR.mkdir(parents=True, exist_ok=True)

PROVIDER = os.getenv("LLM_PROVIDER", "groq")   # groq | mock
GROQ_API_KEY = os.getenv("GROQ_API_KEY", "")
GROQ_URL = "https://api.groq.com/openai/v1/chat/completions"

# Primary model (fast, cheap); retry model (larger, smarter)
GROQ_MODEL_PRIMARY = "llama-3.1-8b-instant"
GROQ_MODEL_RETRY   = "llama-3.3-70b-versatile"

# ── Extraction prompt ─────────────────────────────────────────────────────────

SYSTEM_PROMPT = """You are an invoice data extraction assistant. 
Extract the following fields from the invoice text and return ONLY valid JSON.
No markdown, no explanation, just the JSON object.

Required fields:
{
  "invoice_number": string or null,
  "invoice_date": string (YYYY-MM-DD format) or null,
  "vendor_name": string or null,
  "vendor_address": string or null,
  "bill_to": string or null,
  "po_reference": string or null,
  "currency": string (3-letter code, e.g. USD) or null,
  "line_items": [
    {
      "description": string,
      "quantity": number or null,
      "unit_price": number or null,
      "amount": number
    }
  ],
  "subtotal": number or null,
  "tax_amount": number or null,
  "tax_rate_pct": number or null,
  "total": number or null,
  "payment_terms": string or null,
  "notes": string or null
}

Rules:
- All monetary values as plain numbers (no currency symbols).
- Dates in YYYY-MM-DD format.
- If a field is not present, use null.
- line_items may be an empty list if no line items are visible.
"""


def _cache_key(text: str) -> str:
    return hashlib.sha256(text.encode()).hexdigest()[:32]


def _load_cache(key: str) -> Optional[dict]:
    path = CACHE_DIR / f"{key}.json"
    if path.exists():
        with open(path) as f:
            return json.load(f)
    return None


def _save_cache(key: str, data: dict) -> None:
    path = CACHE_DIR / f"{key}.json"
    with open(path, "w") as f:
        json.dump(data, f, indent=2)


def _call_groq(text: str, model: str) -> dict:
    """Call Groq API, return parsed JSON dict or raise."""
    headers = {
        "Authorization": f"Bearer {GROQ_API_KEY}",
        "Content-Type": "application/json",
    }
    payload = {
        "model": model,
        "messages": [
            {"role": "system", "content": SYSTEM_PROMPT},
            {"role": "user", "content": f"Extract fields from this invoice text:\n\n{text[:4000]}"},
        ],
        "temperature": 0.0,
        "max_tokens": 1024,
        "response_format": {"type": "json_object"},
    }
    resp = httpx.post(GROQ_URL, headers=headers, json=payload, timeout=30)
    resp.raise_for_status()
    content = resp.json()["choices"][0]["message"]["content"]
    return json.loads(content)


def _mock_extract(text: str) -> dict:
    """
    Deterministic mock that parses simple keyword patterns.
    Used when LLM_PROVIDER=mock or Groq is unavailable.
    Handles pdfplumber-style table-linearised text.
    """
    import re

    def find(pattern, default=None, flags=re.IGNORECASE):
        m = re.search(pattern, text, flags)
        return m.group(1).strip() if m else default

    def find_float(pattern, default=None):
        m = re.search(pattern, text, re.IGNORECASE)
        if m:
            try:
                return float(m.group(1).replace(",", "").replace("$", "").replace("£","").replace("€","").strip())
            except ValueError:
                pass
        return default

    # Vendor name — look for lines after VENDOR label in pdfplumber output
    # pdfplumber linearises the 3-col header as: "INVOICE  VENDOR  BILL TO"
    # then the next line contains vendor name in col 2
    vendor_name = None

    # Pattern 1: explicit label
    for pat in [
        r"(?:^|\n)VENDOR\s*\n([A-Z][^\n]{2,80})",
        r"vendor\s*[:\-]\s*([^\n]{3,80})",
        r"from\s*[:\-]\s*([^\n]{3,80})",
        r"supplier\s*[:\-]\s*([^\n]{3,80})",
    ]:
        m = re.search(pat, text, re.IGNORECASE | re.MULTILINE)
        if m:
            candidate = m.group(1).strip()
            if len(candidate) > 3 and candidate.upper() not in ("BILL TO", "INVOICE", "DATE", "VENDOR"):
                vendor_name = candidate
                break

    # Pattern 2: pdfplumber 3-col layout — "Invoice No: INV-X  VendorName  Zamp Finance"
    # Vendor name appears between the invoice number and the bill-to company name
    if not vendor_name:
        m = re.search(
            r"Invoice No:\s*[A-Z0-9\-]+\s+([A-Z][A-Za-z0-9\s&,\.]+?)"
            r"(?:\s+(?:Zamp|Finance|Corp|LLC|Ltd|Inc|Buyer|100\s|\d{3}\s))",
            text
        )
        if m:
            vendor_name = m.group(1).strip()

    # Pattern 3: scan for known company suffixes in the top portion of the doc
    if not vendor_name:
        top_text = text[:800]
        m = re.search(r"\b([A-Z][A-Za-z\s&]{2,40}(?:Ltd|Inc|Co\b|Corp|International|Supplies|Logistics|Parts|World|Mat))\b", top_text)
        if m:
            candidate = m.group(1).strip()
            if candidate.upper() not in ("BILL TO", "INVOICE NO"):
                vendor_name = candidate

    # Invoice number
    inv_no = find(r"invoice\s*(?:no\.?|number|#)\s*[:\-]?\s*([A-Z]{2,6}[-][A-Z0-9]{2,10}[-]\d{4}[-]\d{2,8})")
    if not inv_no:
        inv_no = find(r"invoice\s*(?:no\.?|number|#)\s*[:\-]?\s*([A-Z0-9][-A-Z0-9]{4,25})")

    # Date
    invoice_date = find(r"(?:invoice\s*)?date\s*[:\-]?\s*(\d{4}-\d{2}-\d{2})")

    # PO reference — look for PO-YYYY-NNN pattern specifically
    po_ref = find(r"\b(PO[-\s]?\d{4}[-\s]?\d{3,6})\b")

    # Total
    total = find_float(r"TOTAL\s+DUE\s*[:\$]?\s*([\d,]+\.?\d*)")
    if total is None:
        total = find_float(r"(?:grand\s+)?total\s*[:\-]?\s*[\$£€]?\s*([\d,]+\.?\d*)")

    subtotal   = find_float(r"(?:sub[-\s]?total|subtotal)\s*[:\-]?\s*[\$£€]?\s*([\d,]+\.?\d*)")
    tax_amount = find_float(r"(?:tax|vat|gst)\s*(?:\([\d.]+%\))?\s*[:\-]?\s*[\$£€]?\s*([\d,]+\.?\d*)")
    tax_rate   = find_float(r"(?:tax|vat|gst)\s*\(?([\d.]+)\s*%\)?")
    terms      = find(r"(?:payment\s+)?terms?\s*[:\-]?\s*(Net\s*\d+|Due\s+on\s+receipt)")
    currency   = find(r"\b(USD|EUR|GBP|INR|AUD|CAD|SGD)\b")

    return {
        "invoice_number": inv_no,
        "invoice_date":   invoice_date,
        "vendor_name":    vendor_name,
        "vendor_address": None,
        "bill_to":        find(r"bill\s+to\s*[:\-]?\s*([A-Z][^\n]{3,80})"),
        "po_reference":   po_ref,
        "currency":       currency or "USD",
        "line_items":     [],
        "subtotal":       subtotal,
        "tax_amount":     tax_amount,
        "tax_rate_pct":   tax_rate,
        "total":          total,
        "payment_terms":  terms,
        "notes":          None,
    }


def extract_fields(text: str, file_hash: str = None) -> tuple[dict, str]:
    """
    Main entry point. Returns (extracted_dict, source)
    source is one of: 'cache' | 'groq_primary' | 'groq_retry' | 'mock'
    """
    cache_key = file_hash or _cache_key(text)

    cached = _load_cache(cache_key)
    if cached:
        logger.info("[llm] cache hit %s", cache_key)
        return cached, "cache"

    provider = os.getenv("LLM_PROVIDER", PROVIDER)
    api_key = os.getenv("GROQ_API_KEY", GROQ_API_KEY)

    if provider == "mock" or not api_key:
        result = _mock_extract(text)
        _save_cache(cache_key, result)
        return result, "mock"

    # Try Groq primary
    for attempt, (model, label) in enumerate([
        (GROQ_MODEL_PRIMARY, "groq_primary"),
        (GROQ_MODEL_RETRY,   "groq_retry"),
    ]):
        try:
            result = _call_groq(text, model)
            _save_cache(cache_key, result)
            logger.info("[llm] %s success", label)
            return result, label
        except httpx.HTTPStatusError as e:
            if e.response.status_code == 429 and attempt == 0:
                logger.warning("[llm] rate limited, sleeping 5s then retrying larger model")
                time.sleep(5)
                continue
            logger.error("[llm] HTTP error %s: %s", e.response.status_code, e)
        except Exception as e:
            logger.error("[llm] %s error: %s", label, e)
            if attempt == 0:
                continue

    # Final fallback: mock
    logger.warning("[llm] falling back to mock provider")
    result = _mock_extract(text)
    _save_cache(cache_key, result)
    return result, "mock_fallback"
