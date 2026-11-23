"""
scripts/make_invoices.py
Generates 4 test invoice PDFs covering all demo scenarios:
  1. happy_path.pdf       — clean digital PDF, explicit PO, exact vendor, within tolerance
  2. split_po.pdf         — second invoice against PO-2024-007 (partially consumed)
  3. near_duplicate.pdf   — same vendor/amount/date as a prior invoice, invoice# off by 1 char
  4. scanned_no_po.pdf    — image-only (rasterised) invoice, no PO reference

Run: python scripts/make_invoices.py
"""

import sys
import io
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from reportlab.lib.pagesizes import A4
from reportlab.lib import colors
from reportlab.lib.units import mm
from reportlab.platypus import (
    SimpleDocTemplate, Table, TableStyle, Paragraph, Spacer, HRFlowable
)
from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
from reportlab.lib.enums import TA_RIGHT, TA_CENTER, TA_LEFT

OUT_DIR = Path(__file__).parent.parent / "data" / "invoices"
OUT_DIR.mkdir(parents=True, exist_ok=True)

styles = getSampleStyleSheet()

# ── Shared style helpers ──────────────────────────────────────────────────────

def h1(text):
    return Paragraph(text, ParagraphStyle("h1", fontSize=22, fontName="Helvetica-Bold", textColor=colors.HexColor("#1a1a2e"), spaceAfter=4))

def h2(text):
    return Paragraph(text, ParagraphStyle("h2", fontSize=14, fontName="Helvetica-Bold", textColor=colors.HexColor("#16213e"), spaceAfter=2))

def label(text):
    return Paragraph(text, ParagraphStyle("lbl", fontSize=8, fontName="Helvetica", textColor=colors.HexColor("#888888")))

def body(text, align=TA_LEFT):
    return Paragraph(text, ParagraphStyle("body", fontSize=10, fontName="Helvetica", alignment=align))

def bold(text, align=TA_LEFT):
    return Paragraph(text, ParagraphStyle("bold", fontSize=10, fontName="Helvetica-Bold", alignment=align))

def right(text):
    return Paragraph(text, ParagraphStyle("right", fontSize=10, fontName="Helvetica", alignment=TA_RIGHT))

def bold_right(text):
    return Paragraph(text, ParagraphStyle("bright", fontSize=11, fontName="Helvetica-Bold", alignment=TA_RIGHT))


LINE_ITEM_STYLE = TableStyle([
    ("BACKGROUND",   (0, 0), (-1, 0),  colors.HexColor("#1a1a2e")),
    ("TEXTCOLOR",    (0, 0), (-1, 0),  colors.white),
    ("FONTNAME",     (0, 0), (-1, 0),  "Helvetica-Bold"),
    ("FONTSIZE",     (0, 0), (-1, 0),  9),
    ("ROWBACKGROUNDS", (0, 1), (-1, -1), [colors.white, colors.HexColor("#f8f8f8")]),
    ("FONTSIZE",     (0, 1), (-1, -1), 9),
    ("ALIGN",        (1, 0), (-1, -1), "RIGHT"),
    ("ALIGN",        (0, 0), (0, -1),  "LEFT"),
    ("GRID",         (0, 0), (-1, -1), 0.3, colors.HexColor("#dddddd")),
    ("TOPPADDING",   (0, 0), (-1, -1), 4),
    ("BOTTOMPADDING",(0, 0), (-1, -1), 4),
    ("LEFTPADDING",  (0, 0), (-1, -1), 6),
    ("RIGHTPADDING", (0, 0), (-1, -1), 6),
])

TOTAL_STYLE = TableStyle([
    ("ALIGN",        (0, 0), (-1, -1), "RIGHT"),
    ("FONTSIZE",     (0, 0), (-1, -1), 9),
    ("TOPPADDING",   (0, 0), (-1, -1), 3),
    ("BOTTOMPADDING",(0, 0), (-1, -1), 3),
    ("LINEABOVE",    (0, -1), (-1, -1), 1.5, colors.HexColor("#1a1a2e")),
    ("FONTNAME",     (0, -1), (-1, -1), "Helvetica-Bold"),
    ("FONTSIZE",     (0, -1), (-1, -1), 11),
])


def build_invoice(
    out_path: Path,
    invoice_no: str,
    invoice_date: str,
    vendor_name: str,
    vendor_address: str,
    bill_to: str,
    po_reference: str,
    line_items: list,   # list of (description, qty, unit_price)
    tax_rate_pct: float,
    payment_terms: str = "Net 30",
    notes: str = "",
    total_override: float = None,
):
    """Build a clean, well-formatted digital invoice PDF."""
    doc = SimpleDocTemplate(
        str(out_path),
        pagesize=A4,
        topMargin=15*mm, bottomMargin=15*mm,
        leftMargin=20*mm, rightMargin=20*mm,
    )
    W = A4[0] - 40*mm   # usable width
    story = []

    # ── Header ───────────────────────────────────────────────────────────────
    header_data = [
        [h1("INVOICE"), label("VENDOR"), label("BILL TO")],
        [
            body(f"<b>Invoice No:</b> {invoice_no}"),
            body(vendor_name),
            body(bill_to),
        ],
        [
            body(f"<b>Date:</b> {invoice_date}"),
            body(vendor_address.replace("\n", "<br/>")),
            body(""),
        ],
    ]
    if po_reference:
        header_data.append([body(f"<b>PO Reference:</b> {po_reference}"), body(""), body("")])

    header_data.append([body(f"<b>Terms:</b> {payment_terms}"), body(""), body("")])

    header_table = Table(header_data, colWidths=[W*0.35, W*0.33, W*0.32])
    header_table.setStyle(TableStyle([
        ("VALIGN", (0,0), (-1,-1), "TOP"),
        ("TOPPADDING", (0,0), (-1,-1), 3),
        ("BOTTOMPADDING", (0,0), (-1,-1), 2),
    ]))
    story.append(header_table)
    story.append(Spacer(1, 6*mm))
    story.append(HRFlowable(width="100%", thickness=1.5, color=colors.HexColor("#1a1a2e")))
    story.append(Spacer(1, 4*mm))

    # ── Line items table ──────────────────────────────────────────────────────
    item_rows = [["Description", "Qty", "Unit Price", "Amount"]]
    subtotal = 0.0
    for desc, qty, unit_price in line_items:
        amount = qty * unit_price
        subtotal += amount
        item_rows.append([
            body(desc),
            right(str(qty)),
            right(f"${unit_price:,.2f}"),
            right(f"${amount:,.2f}"),
        ])

    items_table = Table(item_rows, colWidths=[W*0.52, W*0.12, W*0.18, W*0.18])
    items_table.setStyle(LINE_ITEM_STYLE)
    story.append(items_table)
    story.append(Spacer(1, 4*mm))

    # ── Totals ────────────────────────────────────────────────────────────────
    tax_amount = round(subtotal * tax_rate_pct / 100, 2)
    total      = total_override if total_override is not None else round(subtotal + tax_amount, 2)

    totals_data = [
        [body("Subtotal:"),   right(f"${subtotal:,.2f}")],
        [body(f"Tax ({tax_rate_pct}%):"), right(f"${tax_amount:,.2f}")],
        [bold("TOTAL DUE:"), bold_right(f"${total:,.2f}")],
    ]
    totals_table = Table(totals_data, colWidths=[W*0.75, W*0.25])
    totals_table.setStyle(TOTAL_STYLE)
    story.append(totals_table)

    # ── Notes ─────────────────────────────────────────────────────────────────
    if notes:
        story.append(Spacer(1, 6*mm))
        story.append(HRFlowable(width="100%", thickness=0.5, color=colors.HexColor("#cccccc")))
        story.append(Spacer(1, 2*mm))
        story.append(label("NOTES"))
        story.append(body(notes))

    # ── Footer ────────────────────────────────────────────────────────────────
    story.append(Spacer(1, 8*mm))
    story.append(HRFlowable(width="100%", thickness=0.5, color=colors.HexColor("#cccccc")))
    story.append(Spacer(1, 2*mm))
    story.append(Paragraph(
        "Thank you for your business. Please remit payment within terms.",
        ParagraphStyle("footer", fontSize=8, textColor=colors.HexColor("#aaaaaa"), alignment=TA_CENTER)
    ))

    doc.build(story)
    print(f"[make_invoices] ✅ {out_path.name}  —  total ${total:,.2f}")
    return total


# ═══════════════════════════════════════════════════════════════════════════════
# Invoice 1: Happy Path
# Clean digital PDF, explicit PO-2024-001, Acme Supplies Ltd, within 2% tolerance
# ═══════════════════════════════════════════════════════════════════════════════

def make_happy_path():
    # PO-2024-001 total = $10,000. Invoice = $9,980 (within 2% tolerance of $10,000)
    build_invoice(
        out_path=OUT_DIR / "happy_path.pdf",
        invoice_no="INV-ACM-2024-0391",
        invoice_date="2024-04-01",
        vendor_name="Acme Supplies Ltd",
        vendor_address="42 Supplier Row\nNew York, NY 10001\nUSA",
        bill_to="Zamp Finance Corp\n100 Buyer Ave\nSan Francisco, CA 94105",
        po_reference="PO-2024-001",
        line_items=[
            ("Printer paper A4 (case of 10 reams)",   50,  15.00),   # 750
            ("Ballpoint pens, blue, box of 50",        20,   8.00),   # 160
            ("Heavy-duty staples, box of 500",        100,   5.00),   # 500
            ("Spiral notebooks, A5, pack of 10",      100,   7.50),   # 750
            ("Manila folders, pack of 50",            200,   4.00),   # 800
            ("Clear tape rolls, pack of 12",          100,   3.00),   # 300
            ("Whiteboard markers, pack of 10",        100,  12.00),   # 1200
            ("Copy paper 80gsm, box of 5 reams",      100,  18.00),   # 1800
            ("Filing cabinet labels, sheet pack",     200,   2.00),   # 400
            ("Index dividers, pack of 20",            200,   5.00),   # 1000
            ("Letter trays, stackable",               100,   8.20),   # 820
            ("Scissors, office grade",                100,   5.00),   # 500  → total=9980
        ],
        tax_rate_pct=0.0,
        payment_terms="Net 30",
        notes="Delivery completed 2024-03-29. Reference PO-2024-001.",
    )


# ═══════════════════════════════════════════════════════════════════════════════
# Invoice 2: Split PO
# Second invoice against PO-2024-007 (20,000 total, first invoice was $8,000)
# Remaining balance = $12,000. This invoice = $11,800 (within 2% of $12,000)
# ═══════════════════════════════════════════════════════════════════════════════

def make_split_po():
    # PO-2024-007 total = $20,000. First invoice = $8,000 (seeded). Remaining = $12,000.
    # This invoice = $11,760 (within 2% of $12,000) → AUTO APPROVE with split-PO note
    build_invoice(
        out_path=OUT_DIR / "split_po.pdf",
        invoice_no="INV-ACM-2024-0415",
        invoice_date="2024-04-15",
        vendor_name="Acme Supplies Ltd",
        vendor_address="42 Supplier Row\nNew York, NY 10001\nUSA",
        bill_to="Zamp Finance Corp\n100 Buyer Ave\nSan Francisco, CA 94105",
        po_reference="PO-2024-007",
        line_items=[
            ("Floor cleaner concentrate, 5-gallon (60 units)",  60,  12.00),   # 720
            ("Industrial mop heads, pack of 5 (50 packs)",      50,  40.00),   # 2000
            ("Heavy-duty trash bags 55-gal, case (40 cases)",   40,  20.00),   # 800
            ("Paper towel rolls, 12-pack (60 packs)",           60,  60.00),   # 3600
            ("Hand soap dispenser refill, 1L (80 units)",       80,  10.00),   # 800
            ("Disinfectant wipes, case of 12 (50 cases)",       50,  60.00),   # 3000
            ("Broom and dustpan sets",                          20,  42.00),   # 840  → total=11760
        ],
        tax_rate_pct=0.0,
        payment_terms="Net 30",
        notes="Second and final delivery under PO-2024-007. First invoice INV-7001 ($8,000) already submitted.",
    )


# ═══════════════════════════════════════════════════════════════════════════════
# Invoice 3: Near Duplicate
# Same vendor (TechParts International), same amount ($5,750), same date (2024-04-10)
# Invoice number INV-TP-2202 vs prior INV-TP-2201 — edit distance 1 → DUP_002
# ═══════════════════════════════════════════════════════════════════════════════

def make_near_duplicate():
    # Prior invoice: INV-TP-2201, $5,750, 2024-04-10 (seeded)
    # This invoice:  INV-TP-2202, $5,750, 2024-04-10 → edit distance 1 → DUP_002 REVIEW
    build_invoice(
        out_path=OUT_DIR / "near_duplicate.pdf",
        invoice_no="INV-TP-2202",
        invoice_date="2024-04-10",
        vendor_name="TechParts International",
        vendor_address="88 Components Blvd\nAustin, TX 78701\nUSA",
        bill_to="Zamp Finance Corp\n100 Buyer Ave\nSan Francisco, CA 94105",
        po_reference="PO-2024-003",
        line_items=[
            ("Samsung 870 EVO SSD 1TB",         5, 115.00),   # 575
            ("Corsair Vengeance RAM 32GB DDR5",  5, 175.00),   # 875
            ("Noctua NH-D15 CPU Cooler",         5,  95.00),   # 475
            ("EVGA SuperNOVA 650W PSU",          5,  90.00),   # 450
            ("Thermal paste, 10g tube",          5,  15.00),   # 75
            ("Cable management kit",            25,  14.00),   # 350  → total=2800... need 5750
            ("Server rack shelf (2U)",           5, 160.00),   # 800
            ("IEC C13 power cable (2m), 10pk",  10,  32.00),   # 320  → running: 3920
            ("Kingston USB 3.2 32GB (5pk)",     10,  43.00),   # 430  → 4350
            ("HDMI 2.1 cable (2m) 5pk",         10,  28.00),   # 280  → 4630
            ("Anti-static wrist strap (10pk)",  10,  24.00),   # 240  → 4870
            ("Velcro cable ties (100pk)",        10,  18.00),   # 180  → 5050
            ("ESD mat, large",                   5, 140.00),   # 700  → 5750
        ],
        tax_rate_pct=0.0,
        payment_terms="Net 45",
        notes="Server components — batch 2. For any queries contact orders@techparts-intl.com",
    )


# ═══════════════════════════════════════════════════════════════════════════════
# Invoice 4: Scanned / No PO Reference
# Digital version first, then we rasterise it to simulate a scanned document.
# Vendor name uses an alias ("Global Log Co") — tests fuzzy match.
# No PO reference → implied match attempt.
# ═══════════════════════════════════════════════════════════════════════════════

def make_scanned_no_po():
    # First build a clean digital version
    digital_path = OUT_DIR / "_scanned_source.pdf"
    build_invoice(
        out_path=digital_path,
        invoice_no="INV-GLC-2024-0088",
        invoice_date="2024-04-20",
        vendor_name="Global Log Co",        # alias — fuzzy match to "Global Logistics Co"
        vendor_address="7 Freight Lane\nChicago, IL 60601\nUSA",
        bill_to="Zamp Finance Corp\n100 Buyer Ave\nSan Francisco, CA 94105",
        po_reference="",                    # No PO reference!
        line_items=[
            ("LTL freight, Chicago to SF, week of Apr 14", 1, 4200.00),
            ("Fuel surcharge (12%)",                        1,  504.00),
            ("Liftgate service",                            1,  175.00),
        ],
        tax_rate_pct=0.0,
        payment_terms="Net 15",
        notes="No PO was issued for this urgent shipment. Please reference vendor contract GLC-2024.",
    )

    # Rasterise to simulate scanned document
    try:
        import fitz   # PyMuPDF
        from PIL import Image, ImageFilter
        import random

        doc = fitz.open(str(digital_path))
        images = []
        for page in doc:
            mat = fitz.Matrix(1.8, 1.8)
            pix = page.get_pixmap(matrix=mat)
            img = Image.frombytes("RGB", [pix.width, pix.height], pix.samples)
            # Convert to grayscale (scanner effect)
            img = img.convert("L")
            # Add slight blur + noise for realism
            img = img.filter(ImageFilter.GaussianBlur(radius=0.5))
            img = img.convert("RGB")
            images.append(img)

        scanned_path = OUT_DIR / "scanned_no_po.pdf"
        images[0].save(
            str(scanned_path),
            save_all=True,
            append_images=images[1:],
            resolution=150,
        )
        print(f"[make_invoices] ✅ scanned_no_po.pdf  — rasterised ({len(images)} page(s))")
    except ImportError as e:
        # PyMuPDF not installed — just copy the digital version and rename it
        print(f"[make_invoices] ⚠️  PyMuPDF not found ({e}). Using digital version as scanned fallback.")
        import shutil
        shutil.copy(digital_path, OUT_DIR / "scanned_no_po.pdf")
        print(f"[make_invoices] ✅ scanned_no_po.pdf  — (digital fallback, OCR will still run)")


# ═══════════════════════════════════════════════════════════════════════════════
# Invoice 5: Blocked Vendor / Fraud Alert
# Vendor name matches Fraudster Corp (status: blocked in vendor master)
# ═══════════════════════════════════════════════════════════════════════════════

def make_blocked_vendor():
    build_invoice(
        out_path=OUT_DIR / "blocked_vendor.pdf",
        invoice_no="INV-FRD-9901",
        invoice_date="2024-04-18",
        vendor_name="Fraudster Corp",
        vendor_address="99 Shady Lane\nOffshore Haven, CY 99999",
        bill_to="Zamp Finance Corp\n100 Buyer Ave\nSan Francisco, CA 94105",
        po_reference="PO-2024-001",
        line_items=[
            ("Consulting & advisory services retainer", 1, 4500.00),
            ("Expedited processing surcharge",          1,  500.00),
        ],
        tax_rate_pct=0.0,
        payment_terms="Immediate",
        notes="Please wire funds immediately to designated offshore account.",
    )


# ═══════════════════════════════════════════════════════════════════════════════
# Invoice 6: PO Overrun / Exceeds Tolerance Limit
# PO-2024-005 total = $3,200. Invoice = $4,500 (+40.6% over PO limit)
# ═══════════════════════════════════════════════════════════════════════════════

def make_overrun_po():
    build_invoice(
        out_path=OUT_DIR / "overrun_po.pdf",
        invoice_no="INV-OW-2024-104",
        invoice_date="2024-04-22",
        vendor_name="OfficeWorld Inc",
        vendor_address="12 Stationery Plaza\nDallas, TX 75201\nUSA",
        bill_to="Zamp Finance Corp\n100 Buyer Ave\nSan Francisco, CA 94105",
        po_reference="PO-2024-005",
        line_items=[
            ("Premium executive desk chairs",    6, 500.00),   # 3000
            ("Adjustable standing desk converter", 5, 300.00), # 1500  → 4500 total vs 3200 PO
        ],
        tax_rate_pct=0.0,
        payment_terms="Net 30",
        notes="Price increase applied per updated Q2 corporate catalog.",
    )


# ═══════════════════════════════════════════════════════════════════════════════
# Invoice 7: Messy / Unbundled Freight (Reconciled via Policy FIN-POL-01)
# Subtotal $8,100 + Tax $0 != Total $8,450. Discrepancy of $350.
# Footer notes cite unbundled LTL freight delivery fee.
# Reconciler maps to FIN-POL-01 and passes VAL_003.
# ═══════════════════════════════════════════════════════════════════════════════

def make_messy_reconciled():
    build_invoice(
        out_path=OUT_DIR / "messy_reconciled.pdf",
        invoice_no="INV-GLC-2024-9102",
        invoice_date="2024-04-24",
        vendor_name="Global Logistics Co",
        vendor_address="7 Freight Lane\nChicago, IL 60601\nUSA",
        bill_to="Zamp Finance Corp\n100 Buyer Ave\nSan Francisco, CA 94105",
        po_reference="PO-2024-004",
        line_items=[
            ("Dedicated interstate dry-van freight transport", 1, 5500.00),
            ("Pallet staging and cross-docking service",        1, 2600.00),
        ],
        tax_rate_pct=0.0,
        payment_terms="Net 30",
        notes="Invoice total includes $350.00 unbundled LTL freight and delivery handling fee pursuant to logistics services agreement.",
        total_override=8450.00,
    )


if __name__ == "__main__":
    print("Generating test invoices...")
    make_happy_path()
    make_split_po()
    make_near_duplicate()
    make_scanned_no_po()
    make_blocked_vendor()
    make_overrun_po()
    make_messy_reconciled()
    print("\nAll invoices written to data/invoices/")
    print("Files:")
    for f in sorted(OUT_DIR.glob("*.pdf")):
        print(f"  {f.name:35s}  {f.stat().st_size:>8,} bytes")
