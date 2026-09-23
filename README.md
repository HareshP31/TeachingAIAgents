# Teaching AI Agents

Local-first acquisition research and audit system. Slack drives two LangGraph workflows: PDF ingestion (`parse → chunk → embed → store`) and audited conversation runs (`Route → Researcher → Analyst → Auditor → HumanReview → Notify`). A read-only dashboard mirrors Postgres telemetry in real time.

## Teammate quick start

Prerequisites: Git, Docker Desktop with Compose, at least 10 GB free disk, and 16 GB RAM minimum. A 32 GB machine is recommended for real local inference. Docker builds and installs the Python and npm dependencies; no host `npm install` is required for normal use.

The repository ships the complete 28-PDF corpus as `data/guidebooks/drive-download-20260922T024818Z-1-001.zip`. Do not unzip it manually.

```bash
(cd data/guidebooks && shasum -a 256 -c SHA256SUMS)
```

```bash
git clone https://github.com/HareshP31/TeachingAIAgents.git
cd TeachingAIAgents
cp .env.example .env
docker compose up -d --build
docker compose exec -T backend python -m app.cli import-archive /data/guidebooks/drive-download-20260922T024818Z-1-001.zip
```

Open the dashboard at `http://localhost:3000`. Readiness is available at `http://localhost:8000/health/ready`, and API documentation at `http://localhost:8000/docs`.

The default `.env.example` uses deterministic fake mode, so this startup path needs neither LM Studio nor Slack. Fake mode exercises Postgres, pgvector, ingestion, LangGraph, risk scoring, checkpointed review, the REST API, and dashboard. Choose fake or local mode before importing: stored embeddings are mode-specific.

## Run with the real local 7B model, without Slack

1. Install LM Studio and load the exact model ID `qwen/qwen2.5-vl-7b`. Do not use a 27B model.
2. Start LM Studio's OpenAI-compatible server on port `1234`, enable local-network access, and use a context length of at least 4,096 tokens.
3. Before the first corpus import, edit `.env`:

```dotenv
APP_MODE=local
SLACK_ENABLED=false
LM_STUDIO_BASE_URL=http://host.docker.internal:1234/v1
LM_STUDIO_MODEL=qwen/qwen2.5-vl-7b
```

4. Run the same `docker compose up -d --build` and `import-archive` commands from the quick start.

Local mode uses real LM Studio inference, BGE embeddings, Nanobot/public-source research, Postgres, and LangGraph. It retains `/api/dev/runs` and `/api/dev/runs/{run_id}/review` for Slack-free testing.

## Enable Slack/live mode

1. Complete the real-local setup above and confirm `/health/ready` reports ready.
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

Retrieval evaluation ships with 24 corpus cases in `backend/app/evals/corpus_cases.yaml`. Production and evaluation use a 12-chunk evidence window, which reached a 95.65% expected-source hit rate on this corpus. Use `--full` only while the 7B LM Studio server is running; it adds analyst/auditor answer and citation checks.

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

No OpenAI, Anthropic, hosted embedding, or external storage account is used. Runtime inference is pinned to Qwen 2.5 VL 7B; 27B models are rejected to protect this 32 GB host. Slack and live public-web research still require internet access. See [docs/project-architecture-plan.md](docs/project-architecture-plan.md) for the original design and [docs/outstanding-work-plan.md](docs/outstanding-work-plan.md) for the corpus rollout plan.
