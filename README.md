# Teaching AI Agents

A locally-deployed, multi-agent research & audit system for acquisition research, built as a Senior Design class project. It extends a sponsor's original "Researcher/Auditor Critic Loop" concept into a concrete implementation: a LangGraph state machine orchestrating a web-research agent, a document-analysis/RAG agent, and a human-in-the-loop review gate — all running locally, no cloud.

See [docs/project-architecture-plan.md](docs/project-architecture-plan.md) for the full design doc (architecture layers, graph flow, deployment plan, demo script, team roles).

## Layers at a glance

- **Interface:** Slack Bolt (the only place users type) + a read-only Next.js dashboard.
- **Orchestration:** LangGraph, hosted in FastAPI — runs `ConversationGraph` (Route → Researcher → Analyst → Auditor → HumanReview → Notify) per Slack message, and `IngestionGraph` (parse → chunk → embed → store) per uploaded document.
- **Execution:** `nanobot` (sandboxed Researcher — web search, scoped file I/O) and Qwen via LM Studio (Analyst + Auditor — RAG and compliance checks over the guideline corpus).
- **Data:** PostgreSQL + pgvector for chunks, embeddings, LangGraph checkpoints, and run telemetry.

## Repo layout

```
backend/    FastAPI + LangGraph orchestrator, Slack Bolt integration, RAG pipeline
frontend/   Next.js dashboard (read-only mirror of Postgres)
nanobot/    Sandboxed Task Execution Agent config (pulled from its own repo)
docs/       Architecture plan and other design docs
docker-compose.yml   Backend + nanobot sandbox + Postgres/pgvector
```

## Getting started

Full install list is in section 12 of the architecture plan. Short version:

- Python 3.11+, Node.js LTS, Docker Desktop, Git
- [LM Studio](https://lmstudio.ai) installed natively on the host (not containerized) with `Qwen2.5-7B-Instruct` Q4_K_M loaded for dev/demo
- A Slack app with Socket Mode enabled (bot token + app token)

```bash
cp .env.example .env    # fill in Slack tokens, DB creds, LM Studio endpoint
docker compose up -d    # backend + postgres/pgvector + nanobot sandbox
```

Frontend (not yet scaffolded — bootstrap with `npx create-next-app@latest` inside `frontend/` when the dashboard work starts):

```bash
cd frontend
npm install
npm run dev
```

## Team roles

- **Agent Development** — LangGraph orchestration, nanobot Researcher wiring, Qwen Analyst/Auditor prompts + RAG pipeline, FastAPI/Slack glue.
- **Frontend** — Next.js dashboard: document repository, compliance/risk view, graph trace visualizer, audit log stream.
- **Security / Infrastructure** — Docker Compose, nanobot sandbox hardening, local deployment, secrets/config, audit logging pipeline.

See section 11 of the architecture plan for details.
