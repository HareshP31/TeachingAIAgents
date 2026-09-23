FROM python:3.11-slim
RUN apt-get update && apt-get install -y --no-install-recommends bubblewrap ca-certificates && rm -rf /var/lib/apt/lists/*
RUN useradd --create-home --uid 10001 nanobot
WORKDIR /app
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt
COPY app.py .
RUN mkdir -p /workspace && chown -R nanobot:nanobot /workspace /home/nanobot
USER nanobot
ENV HOME=/home/nanobot PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1
CMD ["uvicorn", "app:app", "--host", "0.0.0.0", "--port", "8090"]
