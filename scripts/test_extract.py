import os
import sys
import shutil
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))
from app.stages import ingest, extract

os.environ['LLM_PROVIDER'] = 'mock'

cache_dir = Path('data/llm_cache')
if cache_dir.exists():
    shutil.rmtree(cache_dir)
cache_dir.mkdir(parents=True, exist_ok=True)

files = ['happy_path.pdf', 'split_po.pdf', 'near_duplicate.pdf', 'scanned_no_po.pdf']
for fname in files:
    path = Path('data/invoices') / fname
    if not path.exists():
        print(f"File not found: {fname}")
        continue
    pdf_bytes = path.read_bytes()
    ing = ingest.run(pdf_bytes, fname, 'test_run')
    ext = extract.run(pdf_bytes, ing['file_hash'], ing['pdf_type'])
    f = ext['fields']
    print(f"=== {fname} ({ing['pdf_type']}) ===")
    print(f"  vendor_name:    {f.get('vendor_name')}")
    print(f"  invoice_number: {f.get('invoice_number')}")
    print(f"  total:          {f.get('total')}")
    print(f"  po_reference:   {f.get('po_reference')}")
    print(f"  invoice_date:   {f.get('invoice_date')}")
    print(f"  missing:        {ext.get('missing_critical')}")
    print()
