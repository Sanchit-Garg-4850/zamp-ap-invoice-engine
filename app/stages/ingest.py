"""
stages/ingest.py — Stage 1: Ingest
- Hash the uploaded file
- Create a run record
- Detect whether the PDF has a text layer (digital) or is image-only (scanned)
"""

import hashlib
import time
from pathlib import Path
from typing import BinaryIO

import pdfplumber


def hash_file(file_bytes: bytes) -> str:
    return hashlib.sha256(file_bytes).hexdigest()


def detect_pdf_type(file_bytes: bytes) -> str:
    """
    Returns 'digital' if the PDF has extractable text on the first page,
    otherwise 'scanned'.
    """
    try:
        import io
        with pdfplumber.open(io.BytesIO(file_bytes)) as pdf:
            for page in pdf.pages[:2]:  # check first 2 pages
                text = page.extract_text() or ""
                if len(text.strip()) > 50:
                    return "digital"
        return "scanned"
    except Exception:
        return "scanned"


def run(file_bytes: bytes, filename: str, run_id: str) -> dict:
    """
    Returns stage event payload.
    """
    t0 = time.time()

    file_hash = hash_file(file_bytes)
    file_size = len(file_bytes)
    pdf_type = detect_pdf_type(file_bytes)

    duration_ms = int((time.time() - t0) * 1000)

    return {
        "stage": "ingest",
        "status": "ok",
        "duration_ms": duration_ms,
        "file_hash": file_hash,
        "file_size_bytes": file_size,
        "filename": filename,
        "pdf_type": pdf_type,   # 'digital' | 'scanned'
        "run_id": run_id,
    }
