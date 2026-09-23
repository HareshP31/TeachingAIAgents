# Outstanding Work Plan

## Current baseline

- The source archive is `data/guidebooks/drive-download-20260922T024818Z-1-001.zip`.
- Archive inspection found 28 PDFs, 91.1 MB compressed, no non-PDF files, no unsafe paths, and no duplicate basenames.
- PostgreSQL with pgvector, LangGraph checkpointing, the FastAPI backend, Nanobot adapter, and the dashboard are implemented.
- Real local inference is pinned to `qwen/qwen2.5-vl-7b`; no 27B model is ever loaded or called.
- Slack-free live tests passed for structured output, guidebook RAG, live research, risk gating, restart recovery, human-review interruption, and dashboard rendering.
- The production corpus is ready: 28 PDFs, 2,372 pages, 2,332 chunks, three OCR documents, and one retained historical version. Slack remains disabled pending workspace credentials.

## Delivery strategy

Work proceeds through six gates. A gate is complete only when its acceptance checks pass; a successful build alone is not completion. Phases 1–4 and 6 can be completed without user intervention. Phase 5 needs Slack workspace credentials and installation authority.

## Phase 1 — Corpus validation and controlled extraction

1. Preserve the ZIP as the immutable source artifact.
2. Extract into a dated staging directory, never directly over existing files.
3. Reject absolute paths, traversal paths, symlinks, encrypted PDFs, and non-PDF payloads.
4. Create a corpus manifest containing:
   - SHA-256
   - original and normalized filename
   - byte size and page count
   - encryption status
   - extracted character count and text-per-page ratio
   - document date/version inferred from filename or metadata
   - ingestion eligibility and failure reason
5. Detect exact-content duplicates and version families. Retain historical versions but mark the newest version as canonical; the two AAF Quick Reference Card versions are an expected version family.
6. Flag image-only or low-text PDFs for OCR rather than silently indexing empty content.

Acceptance gate:

- All 28 archive entries appear in the manifest.
- Every file is classified as text-ready, OCR-required, duplicate, superseded, or rejected.
- Extraction is repeatable and cannot overwrite unrelated files.

## Phase 2 — Production corpus ingestion

1. Add a safe archive-import command so operators do not manually unzip files.
2. Ingest eligible PDFs through the existing IngestionGraph.
3. Make ingestion idempotent by document SHA-256.
4. Store document-level failures without rolling back successful documents.
5. Verify chunk metadata includes document ID, filename, page number, chunk index, and source hash.
6. Verify every vector has the configured BGE embedding dimension and can be queried through pgvector.
7. Remove the synthetic fixture after real-corpus validation succeeds.

Acceptance gate:

- Re-importing the same ZIP creates zero duplicate documents or chunks.
- Every eligible PDF has a nonzero chunk count and searchable vectors.
- A failed PDF cannot corrupt or block the rest of the batch.
- Dashboard document counts match PostgreSQL counts.

## Phase 3 — Retrieval and answer-quality evaluation

1. Build a versioned evaluation set of at least 24 questions across:
   - Adaptive Acquisition Framework pathways
   - software acquisition and DevSecOps
   - source selection and competition
   - risk, issue, and opportunity management
   - systems and mission engineering
   - test, sustainment, and product support
2. Record expected source documents and relevant pages for each question; do not require exact prose.
3. Add adversarial cases:
   - answer absent from corpus
   - conflicting or superseded guidance
   - misleading premise
   - request requiring live research rather than guidebook retrieval
   - unsupported dollar amount or vendor claim
4. Measure retrieval hit rate, page-level citation validity, unsupported-claim rate, route correctness, Auditor behavior, revision count, and risk-gate correctness.
5. Tune chunking, overlap, top-k retrieval, prompts, and citation formatting using evaluation results.
6. Require the Analyst to state when evidence is insufficient instead of filling gaps.

Acceptance gate:

- Expected source appears in top-five retrieval for at least 90% of grounded cases.
- Every factual guidebook claim has a stored document/page citation.
- Zero fabricated URLs or document names in the final evaluation run.
- All high-risk cases pause; all clearly low-risk grounded cases auto-complete.

## Phase 4 — Research, reliability, and operational hardening

1. Upgrade live research from search-result snippets to fetched, allowlisted source passages.
2. Store source URL, retrieval time, content hash, passage, and fetch status with each finding.
3. Preserve the bounded DuckDuckGo fallback, but expose whether Nanobot tool use or fallback produced each finding.
4. Enforce SSRF protection, domain allowlists, redirect validation, response-size limits, and timeouts.
5. Add failure-path tests for LM Studio unavailable, Nanobot timeout, malformed structured output, Postgres restart, and partial ingestion.
6. Add single-request model concurrency and memory-safety guidance for the 32 GB Mac.
7. Implement PostgreSQL plus document-store backup and a tested restore procedure.
8. Add retention and cleanup commands for synthetic documents, failed runs, checkpoints, and stale media.
9. Replace default database credentials for live mode and verify secrets never enter Git or logs.

Acceptance gate:

- Research citations resolve to stored allowlisted passages, not only search snippets.
- Backend returns controlled errors instead of HTTP 500 for dependency failures.
- A backup restores documents, vectors, run history, and paused checkpoints on a clean stack.
- Full tests complete with no swap growth or unsafe model concurrency.

## Phase 5 — Slack end-to-end activation

User-required actions:

1. Import `slack-app-manifest.yaml` into the target Slack workspace.
2. Install the app and create an app-level token with `connections:write`.
3. Provide the local `xoxb` bot token and `xapp` app token in `.env`; never paste them into chat or commit them.
4. Invite the app to a dedicated test channel.

Implementation and verification after credentials exist:

1. Switch to `APP_MODE=live` and `SLACK_ENABLED=true` while keeping the 7B model pinned.
2. Test channel mentions and direct messages.
3. Test PDF upload, duplicate upload, unsupported file, oversized file, and low-text PDF behavior.
4. Test threaded responses and idempotency for repeated Slack events.
5. Test approve and reject buttons, including approval after a backend restart.
6. Confirm private requests, files, and review actions cannot leak into another channel or user context.
7. Confirm Slack receives concise errors while detailed diagnostics remain local.

Acceptance gate:

- Mention, DM, upload, grounded response, approval, rejection, and restart-resume flows pass in Slack.
- Duplicate Slack events never create duplicate runs or documents.
- Slack tokens remain local and all requested scopes are justified.

## Phase 6 — Final acceptance and handoff

1. Remove synthetic test data and mark superseded guidebooks in the corpus manifest.
2. Run the complete automated suite and a clean-machine bootstrap rehearsal.
3. Run the 10–15 minute demonstration script using real documents and live sources.
4. Capture a final acceptance report containing versions, test results, known limits, recovery steps, and resource settings.
5. Update README/operator instructions from observed commands and timings.
6. Commit the implementation in reviewable groups and create a demo-ready tag.

Final definition of done:

- A new operator can start the stack, ingest the archive, ask grounded questions, obtain traceable citations, complete human review, inspect the dashboard, restart services, and restore from backup using only documented steps.
- The only continuing external requirements are the local LM Studio server, Docker Desktop, internet access for public research and Slack, and valid Slack credentials.

## Recommended execution order

1. Phase 1 corpus audit
2. Phase 2 ingestion
3. Phase 3 retrieval evaluation and tuning
4. Phase 4 research and resilience hardening
5. Phase 5 Slack activation
6. Phase 6 acceptance, cleanup, and handoff

Do not begin Slack activation before the real corpus passes the retrieval evaluation. This keeps model, retrieval, and citation defects separate from messaging-integration defects.
