# Teaching AI Agents

Local-first acquisition research and audit system. Slack drives two LangGraph workflows: PDF ingestion (`parse → chunk → embed → store`) and audited conversation runs (`Route → Researcher → Analyst → Auditor → HumanReview → Notify`). A read-only dashboard mirrors Postgres telemetry in real time.

## Quick start (real local inference)

Prerequisites: Git, Docker Desktop with Compose, LM Studio, at least 10 GB free disk, and 16 GB RAM minimum. Docker builds and installs the Python and npm dependencies; no host `npm install` is required for normal use. A dedicated GPU is not required, but one materially speeds up inference — the full stack (LangGraph, real BGE embeddings, and a locally-served Qwen2.5-7B-Instruct model backing every reasoning node) has been validated end-to-end on a 4 GB-VRAM laptop GPU with partial layer offload, not just high-end hardware.

1. Install LM Studio, load `qwen2.5-7b-instruct`, and start its OpenAI-compatible server on port `1234` with local-network access enabled. Set its **Context Length to at least 16,384 tokens**. This is higher than a simple chat reply needs — Nanobot's own research/tool-use reasoning carries real overhead per turn, and a smaller window causes its live-research calls to silently fail over to a plain web-search fallback instead of using the model directly.
2. The repository ships the complete 28-PDF corpus as `data/guidebooks/drive-download-20260922T024818Z-1-001.zip`. Do not unzip it manually. Verify it:

```bash
(cd data/guidebooks && shasum -a 256 -c SHA256SUMS)
```

3. Clone and configure:

```bash
git clone https://github.com/HareshP31/TeachingAIAgents.git
cd TeachingAIAgents
cp .env.example .env
```

Edit `.env`:

```dotenv
APP_MODE=local
SLACK_ENABLED=false
LM_STUDIO_BASE_URL=http://host.docker.internal:1234/v1
LM_STUDIO_MODEL=qwen2.5-7b-instruct
NANOBOT_CONTEXT_TOKENS=16384
```

`NANOBOT_CONTEXT_TOKENS` must match whatever context length you actually set in LM Studio in step 1 — the two are independent settings that both need to agree.

4. Build, start, and import the corpus:

```bash
docker compose up -d --build
docker compose exec -T backend python -m app.cli import-archive /data/guidebooks/drive-download-20260922T024818Z-1-001.zip
```

Open the dashboard at `http://localhost:3000`. Readiness is available at `http://localhost:8000/health/ready`, and API documentation at `http://localhost:8000/docs`.

This path uses real LM Studio inference, real BGE embeddings, real Nanobot/public-source research, Postgres, and LangGraph throughout — nothing in it is simulated. It also exposes `/api/dev/runs` and `/api/dev/runs/{run_id}/review` so the full pipeline can be exercised without Slack.

## Enable Slack/live mode

1. Complete the setup above and confirm `/health/ready` reports ready.
2. Import [slack-app-manifest.yaml](slack-app-manifest.yaml) into the target Slack workspace.
3. Install the app, invite it to a dedicated test channel, and create an app-level token with `connections:write`.
4. Put the `xoxb` bot token and `xapp` app token only in local `.env`; never commit or paste them into chat.
5. Set `APP_MODE=live` and `SLACK_ENABLED=true`, then run `docker compose up -d --build`.

Mention the app or send it a DM. PDFs shared in a channel containing the app are ingested automatically. Human-review buttons resume the persisted LangGraph thread after a delay or backend restart. The dev-only run/review endpoints are disabled in live mode.

The archive importer rejects unsafe paths and suspicious compression, hashes every source, OCRs scan-heavy PDFs, preserves historical versions, and marks the newest version canonical. Imports are resumable and idempotent by archive and document hash. The backend image includes Tesseract, Ghostscript, qpdf, and AES-PDF support.

## Operator commands

```bash
docker compose exec backend python -m app.cli always-review true
docker compose exec backend python -m app.cli always-review false
docker compose exec backend python -m app.cli ingest /data/guidebooks
docker compose exec backend python -m app.cli import-archive /data/guidebooks/drive-download-20260922T024818Z-1-001.zip
docker compose exec backend python -m app.cli corpus-status
docker compose exec backend python -m app.cli eval-corpus --output /data/documents/eval-report.json
docker compose exec backend python -m app.cli eval-corpus --full --output /data/documents/eval-report-full.json
docker compose exec backend python -m app.cli cleanup failed
python3 scripts/smoke.py
```

Retrieval evaluation ships with 24 corpus cases in `backend/app/evals/corpus_cases.yaml`. Production and evaluation use a 12-chunk evidence window, which reached a 95.65% expected-source hit rate on this corpus. Use `--full` only while the LM Studio server is running; it adds real Analyst/Auditor answer and citation checks.

## Backup and recovery

```bash
./scripts/backup.sh backups
RESTORE_CONFIRM=teaching-ai-agents ./scripts/restore.sh backups/<timestamp>
```

Backups contain a custom-format Postgres dump, document-volume archive, guidebook archive, environment template, and SHA-256 manifest. Restore verifies checksums and moves the current guidebook directory to a timestamped recovery path before replacement. Treat restore as destructive and stop active imports first.

Health: `http://localhost:8000/health/ready`. Dashboard: `http://localhost:3000`. API documentation: `http://localhost:8000/docs`.

## Verification

Docker-based verification needs no host dependency install. For host-side development, install the lockfile dependencies first:

```bash
python3 -m venv .venv
.venv/bin/python -m pip install -r backend/requirements-dev.txt
(cd frontend && npm ci)
(cd backend && ../.venv/bin/python -m pytest)
(cd frontend && npm run build)
docker compose config --quiet
bash -n scripts/backup.sh scripts/restore.sh
```

No OpenAI, Anthropic, hosted embedding, or external storage account is used. Runtime inference is pinned to Qwen2.5-7B-Instruct; 27B models are rejected to keep inference within reach of modest hardware. Slack and live public-web research still require internet access. See [docs/project-architecture-plan.md](docs/project-architecture-plan.md) for the original design and [docs/outstanding-work-plan.md](docs/outstanding-work-plan.md) for the corpus rollout plan.
