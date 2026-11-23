FROM python:3.11-slim

# Install system dependencies including tesseract-ocr
RUN apt-get update && apt-get install -y --no-install-recommends \
    tesseract-ocr \
    libtesseract-dev \
    gcc \
    curl \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

# Install python dependencies
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Copy application code
COPY . .

# Generate test PDFs and seed DB on build
RUN python scripts/make_invoices.py && python scripts/seed.py

EXPOSE 8000

ENV PORT=8000
ENV LLM_PROVIDER=mock

CMD ["sh", "-c", "uvicorn app.main:app --host 0.0.0.0 --port ${PORT:-8000}"]
