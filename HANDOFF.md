# Handoff — Local Setup, Debugging & Live-Slack Validation Session

**Date:** 2026-09-23 through 2026-09-29
**Machine this was done on:** Windows 11, RTX 3050 Laptop (4GB VRAM), 15.6GB RAM, Docker Desktop + WSL2, LM Studio running `qwen2.5-7b-instruct` (Q4_K_M)
**Starting point:** fresh clone, README-only setup
**Ending point:** full pipeline (Docker + LangGraph + real Qwen + real Nanobot + real Slack) verified working end-to-end on constrained consumer hardware

This is a working log, not a spec — for the actual architecture, see [docs/project-architecture-plan.md](docs/project-architecture-plan.md). This file exists so a teammate (or a future session) doesn't have to re-derive what's already been proven and what hasn't.

---

## 1. What's confirmed working, on this exact hardware

- **Docker stack** — postgres (pgvector), nanobot, backend, frontend all build and run via `docker compose up -d`. Frontend can be omitted (`docker compose up -d postgres nanobot backend`) to save ~1GB during heavy CLI testing.
- **Real corpus import** — all 28 guidebook PDFs, 2,372 pages, 2,332 chunks, 0 failed, real BGE (`BAAI/bge-large-en-v1.5`) embeddings on CPU. Took ~52 minutes on this hardware (one-time cost; survives `docker compose stop`/`start`, only wiped by `down -v`).
- **Real Qwen inference via LM Studio** — `qwen2.5-7b-instruct`, GPU-offloaded (partial — full model doesn't fit in 4GB VRAM alone, LM Studio auto-splits GPU/CPU). Confirmed via `nvidia-smi` utilization spikes during generation.
- **Full ConversationGraph, real LLM calls** — Route → Analyst → Auditor → (reject loop) → Researcher → Analyst → Auditor → HumanReview → Notify, all firing for real, tested via `/api/dev/runs` multiple times. Typical full run (with one revision loop): **120–215 seconds** on this hardware.
- **`eval-corpus --full`** — 24/24 cases, **95.7% source hit rate** (matches README's claimed baseline exactly), 100% behavior pass rate, 82.6% citation validity, 91.7% auditor pass rate. Report at `/data/documents/evaluations/local-full.json` inside the backend container.
- **Real Nanobot agent path** (not the ddgs fallback) — confirmed working after fixing two real bugs (see §2). Verified via direct CLI invocation and via a live production run that used `source_mode: nanobot` with a genuinely fresh live result.
- **Real Slack integration, full live loop** — Socket Mode connected ("⚡️ Bolt app is running!"), `@mention` triggered a real run, HumanReview posted an Approve/Reject card to the thread, clicking Approve resumed the paused LangGraph checkpoint and delivered the final answer back to Slack. This is the actual production path, not a dev shortcut.

---

## 2. Bugs found and fixed this session (both committed & pushed, commit `13380d1`)

### Bug 1 — Nanobot's context window didn't match LM Studio's loaded model
Nanobot's own config framework defaults `contextWindowTokens` to 200,000 and `maxTokens` (output) to 8192. [nanobot/app.py](nanobot/app.py)'s `configure_nanobot()` never overrode either, so Nanobot believed it had a 200k window against a model actually loaded with far less — every real research call silently overflowed and errored, and the backend swallowed that error, **always** falling back to plain DuckDuckGo search. Looked like "Nanobot is working" but never actually exercised its own reasoning.

**Fix:** `configure_nanobot()` now sets both explicitly from env vars (`NANOBOT_CONTEXT_TOKENS`, default 16384; `NANOBOT_MAX_OUTPUT_TOKENS`, default 1024). **Also had to bump LM Studio's actually-loaded context from 8192 → 16384** (`lms load qwen2.5-7b-instruct -c 16384`) — fits fine, only +0.4GB estimated VRAM need since KV cache is cheap relative to model weights at this size. **If your teammate reloads the model in LM Studio, they must set Context Length to 16384 (or update `NANOBOT_CONTEXT_TOKENS` to match whatever they load) — this does not persist automatically across reloads unless saved as a load preset.**

### Bug 2 — Hardcoded 30-second subprocess timeout, too tight for this hardware
The `/research` handler killed Nanobot's own agent subprocess after a hardcoded 30s. First real successful test took 29.65s — right at the edge, and real production questions (with audit-feedback context on revision passes) can run longer.

**Fix:** now configurable via `NANOBOT_AGENT_TIMEOUT_SECONDS` (default 100s), comfortably under the outer `NANOBOT_TIMEOUT_SECONDS=150` HTTP budget so there's still room for the ddgs fallback to run if needed.

### Bonus fix — Nanobot had zero logging
Added `logging.basicConfig` + explicit log lines on timeout, non-zero exit, and fallback-triggered. Previously all of this was silently swallowed — this is what made bugs 1 & 2 debuggable at all; without it, diagnosing today's issue would have required re-deriving everything from scratch again next time.

**Known soft spot, not a bug:** even fixed, a given research call can still fall back to ddgs if Qwen's answer happens not to include a raw `https://...` URL in its prose (the extraction is regex-based over final text). This is model-phrasing variance, not a timeout/crash — logs now say exactly why (`nanobot agent returned no allowlisted URL, falling back to ddgs`). See §4 for the fix idea.

---

## 3. Things I did NOT expect to matter but did (environment gremlins)

- **Git Bash path mangling** — any `docker compose exec` argument starting with `/data/...` or `/home/...` gets silently rewritten to `C:/Program Files/Git/data/...` by MSYS. Prefix the command with `MSYS_NO_PATHCONV=1` whenever passing a container-absolute path.
- **`lms load` doesn't replace an already-loaded instance** — reloading with a different context length creates a second identifier (`qwen2.5-7b-instruct:2`) rather than swapping it, and both stay loaded simultaneously (nearly OOM'd at 3.85GB/4GB). Always `lms unload <both identifiers>` before reloading with new settings, then load once with `--identifier <original-name>` to keep `.env`'s `LM_STUDIO_MODEL` reference valid.
- **`.env` had duplicate keys** at one point (Slack tokens appended at the bottom while placeholder lines stayed at the top) — python-dotenv takes the *last* occurrence, so it technically worked, but cleaned it up to avoid future ambiguity.

---

## 4. What's left toward the full architecture-doc plan

Roughly in the order I'd tackle them:

1. **PDF ingestion via Slack (IngestionGraph)** — drag a new DAU PDF into the channel, confirm `file_shared` → ingestion → dashboard/Postgres updates. User is sourcing more DAU documents for this next.
2. **Validate the auto-approve path** — every real run so far (3 for 3) has landed on risk score 80 / forced HumanReview escalation. The architecture doc's own step-1 demo question is supposed to score ~0 and go straight to `Notify` with **no** pause. This side of the risk-threshold split has never actually been observed firing on this hardware — worth deliberately testing before assuming it works.
3. **Dashboard, fully verified against real (non-fake) data** — the Next.js frontend ([frontend/app/page.tsx](frontend/app/page.tsx)) is a complete, real implementation (not a stub) that polls `/api/overview`, `/health/ready`, `/api/runs/{id}` — it's just never been opened and eyeballed rendering our actual local-mode runs. `docker compose up -d frontend`, open `localhost:3000`.
4. **The "blocked action" security moment** (architecture doc §7, demo beat 5) — ask the agent to do something outside Nanobot's sandbox scope (e.g. read a file outside its staging directory) and confirm it's denied *and logged*. Never tested this session.
5. **`ALWAYS_REVIEW` toggle** — never exercised. `docker compose exec backend python -m app.cli always-review true` forces every run through HumanReview regardless of risk score (see chat log for full mechanics — Approve/Reject already do exactly "accept as-is" / "refire the graph via Researcher" respectively, this toggle just changes when that prompt appears).
6. **Backend's own `pytest` suite** — never run this session. Should be step zero before trusting further changes, especially since `nanobot/app.py` was hand-edited today with zero test coverage of its own.
7. **Nanobot test coverage (currently zero)** — concrete candidates: `configure_nanobot()` config-generation correctness (would have caught bug 1 immediately), `is_allowed_url()` allowlist logic, `host_is_public()` SSRF protection, `/research` fallback branching (mock the subprocess for timeout/error/success cases), `fetch_finding()`'s size-cap/redirect-cap/content-type guards.
8. **URL-citation hardening for Nanobot's real path** — either strengthen the research prompt to demand explicit URL citation, or read URLs from Nanobot's own tool-call history (`workspace/memory/history.jsonl`) instead of only regexing final response text. Would reduce how often a genuinely-successful real Nanobot call still gets counted as a fallback.
9. **`scripts/backup.sh` / `restore.sh`** — untested this session. Given the Git-Bash path-mangling issues hit elsewhere, worth a dry run before relying on either, particularly `restore.sh` since it's destructive (drops/rebuilds Postgres, wipes `/data/documents`, moves aside `data/guidebooks`).
10. **Demo pacing** — real full runs take 120–215 seconds each on this hardware. Two demo questions plus a security moment in a 10–15 minute window is tight; worth a timed full rehearsal once ingestion (#1) is done.
11. **Multi-teammate Slack usage** — if a teammate wants to run their *own* parallel backend against the *same* Slack app/tokens, both instances receive every event and would double-respond (Slack allows multiple concurrent Socket Mode connections per app). Fine if only one person runs the backend while others just type in Slack; needs a second Slack app (own token pair) if true parallel local dev is wanted.
12. **Let a Slack reviewer type *why* they're rejecting, not just click Reject** — the plumbing already exists end to end: `ReviewDecision.note` ([schemas.py:66](backend/app/schemas.py:66)) flows into a `CitationIssue` on rejection ([conversation_graph.py:166-170](backend/app/graphs/conversation_graph.py:166)), which the real Analyst reads back as `audit_feedback` on the next revision pass ([analyst.py:67](backend/app/agents/analyst.py:67)) — confirmed via the dev API, which already accepts a free-text `note` in its POST body and has it reach the next Analyst call. The gap is Slack-specific: the Reject *button* ([bolt_app.py:136-137](backend/app/slack/bolt_app.py:136)) hardcodes `note="Reviewer requested revision"` because a button click carries no free text.
    **Confirmed feasible with no new dependencies or Slack scopes:** checked directly against the pinned packages in this repo — `slack_bolt.async_app.AsyncApp` already exposes `.view()` for handling modal submissions, and `slack_sdk.web.async_client.AsyncWebClient` already exposes `.views_open()` for opening one. The manifest's existing `interactivity.is_enabled: true` is all Slack requires for both (no extra OAuth scope). Every block-action payload (the Reject click) already includes a `trigger_id`, which is exactly what `views_open` needs and is only valid for ~3 seconds — so it must be used immediately in the same handler, not after any other await.
    **Shape of the fix:** change the Reject action handler to call `client.views_open(trigger_id=body["trigger_id"], view={...one text input block..., "private_metadata": json.dumps({run_id, thread_id, channel, thread_ts})})` instead of resolving immediately; add a new `@app.view("<callback_id>")` handler that reads the submitted text + `private_metadata`, builds `ReviewDecision(approved=False, note=<typed text>)`, and calls `graph.resume(...)` exactly as `_resume_review` does today. Approve stays a plain button (no text needed). LangGraph's Postgres checkpointer already tolerates arbitrarily long pauses (that's the whole point of the interrupt design), so the extra time a reviewer takes typing in the modal changes nothing architecturally.

---

## 5. Current `.env` state (values, not secrets — tokens live only in the actual file)

```
APP_MODE=live
SLACK_ENABLED=true
LM_STUDIO_BASE_URL=http://host.docker.internal:1234/v1
LM_STUDIO_MODEL=qwen2.5-7b-instruct
NANOBOT_CONTEXT_TOKENS=16384      # must match LM Studio's loaded context length
NANOBOT_MAX_OUTPUT_TOKENS=1024
NANOBOT_AGENT_TIMEOUT_SECONDS=100
```
Corpus is imported and ready under this exact `APP_MODE`/`EMBEDDING_MODEL` combination — switching `APP_MODE` to `fake` or changing `EMBEDDING_MODEL` requires `docker compose down -v` + full reimport (fake and real embeddings live in incompatible vector spaces).

Frontend was stopped mid-session to save resources during heavy CLI testing — currently **not running**. `docker compose up -d frontend` to bring it back.

---

## 6. For a teammate picking this up fresh

1. Clone the repo, everything in §2's fixes is already on `origin/main` (commit `13380d1`).
2. Install LM Studio, load `qwen2.5-7b-instruct`, **set Context Length to 16384**, start the server on port 1234 with local-network access on.
3. `cp .env.example .env`, then set `APP_MODE=local` (or `live` if Slack is wanted) and fill in `LM_STUDIO_MODEL=qwen2.5-7b-instruct`.
4. `docker compose up -d --build`, then `docker compose exec -T backend python -m app.cli import-archive /data/guidebooks/drive-download-20260922T024818Z-1-001.zip` (one-time, ~50 min on similarly modest hardware).
5. For Slack access: just be invited to the workspace + the bot's channel as a normal member. No separate app/tokens needed unless running a second, independent backend instance simultaneously (see §4.11).
