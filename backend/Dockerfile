FROM python:3.11-slim

WORKDIR /app

RUN apt-get update && apt-get install -y --no-install-recommends \
    ghostscript qpdf tesseract-ocr && \
    rm -rf /var/lib/apt/lists/*

COPY requirements.txt .
# The default Linux index can resolve CUDA wheels even on Apple Silicon's Linux VM.
# Install the CPU wheel first; sentence-transformers then reuses it.
RUN pip install --no-cache-dir torch --index-url https://download.pytorch.org/whl/cpu && \
    pip install --no-cache-dir -r requirements.txt

COPY app ./app

RUN useradd --create-home --uid 10001 appuser && mkdir -p /data/documents /data/guidebooks /model-cache && chown -R appuser:appuser /data /model-cache /app
USER appuser
ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1 HF_HOME=/model-cache

CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]
