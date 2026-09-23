# Acceptance report

Date: 2026-09-23

## Delivered state

- Runtime: Docker Compose with healthy Postgres/pgvector, backend, Nanobot adapter, and frontend.
- Inference: `qwen/qwen2.5-vl-7b` through LM Studio in local mode. Local/live validation rejects 27B model identifiers.
- Corpus: 28/28 PDFs ready, 2,372 pages, 2,332 chunks, 25 native-text PDFs, three OCR PDFs, 27 canonical documents, and one historical AAF version.
- Import: archive path validation, ZIP-bomb and size limits, streaming hashes, per-file failure isolation, retry of failed hashes, idempotent re-import, AES empty-password support, OCR, and version-family canonicalization.
- Retrieval: 24 cases, 23 grounded cases, 95.65% expected-source hit rate with a 12-chunk evidence window. The remaining miss is `agile-principles`, where the related Agile acquisition guide outranks the expected Agile primer.
- Historical retrieval: a matched version family reserves evidence slots for both the current and superseded AAF cards.
- Model safety: guidebook and web evidence are dynamically compacted for the model's 4,096-token context. All evaluation and live workflow calls used only the 7B model.
- Citation safety: complete filenames and stored page coordinates are required; comma-containing filenames validate correctly; citation issues force an invalid audit.
- Public research: allowlisted URLs are fetched with redirect, DNS/IP, content-type, size, and timeout controls. Successful pages retain fetch time, HTTP status, content hash, source mode, and snippet/full-text status.
- Human review: an unsupported Cloud One answer was rejected for two revisions and persisted as `awaiting_review` with risk 80 and four citation issues instead of being auto-approved.
- Dashboard: corpus import progress, extraction method, page/chunk counts, and canonical/historical state are exposed through `/api/overview` and rendered in the document panel.
- Recovery: backup completed and all checksums validated. Restore syntax and destructive confirmation guard were tested; a destructive restore into the live verified stack was intentionally not run.

## Verification evidence

- Backend: 22 tests passed, 98% statement coverage.
- Frontend: Next.js production build and TypeScript checks passed.
- Static/runtime: Python compile, Compose config, backup/restore shell syntax, and all readiness checks passed.
- Retrieval report: `/data/documents/eval-report.json` in the persistent document volume.
- Full model report: `/data/documents/eval-report-full.json` in the persistent document volume.
- Citation smoke report: `/data/documents/eval-report-citation-smoke.json` in the persistent document volume.
- Test backup: `/private/tmp/teaching-ai-agent-backups/teaching-ai-agents-20260923T120931Z` (ephemeral host storage).

## Remaining operator actions

1. Create/install the Slack app from `slack-app-manifest.yaml`, create the `xapp` token, and invite the app to a dedicated test channel.
2. Put `SLACK_BOT_TOKEN` and `SLACK_APP_TOKEN` only in local `.env`; set `APP_MODE=live` and `SLACK_ENABLED=true`. Keep the exact 7B model ID unchanged.
3. Replace the default Postgres password before any network-exposed/live deployment and update `.env` accordingly.
4. Run Slack mention, DM, PDF upload/duplicate/oversize, approve/reject, and restart-resume acceptance cases.
5. Schedule a maintenance window for a clean-stack restore drill using the documented confirmation token. Do not test restore against the only live copy.
6. Review or reject the pending local research run in the dashboard/dev API, then run `python -m app.cli cleanup synthetic` if the retained test history is no longer useful.
7. Review the working-tree changes, commit them in the desired grouping, and create a demo-ready tag. No commit or tag was created automatically because the repository already contained user-owned changes.

## Known limits

- Public research used the DDGS fallback during acceptance; four of five results were still fully fetched and hashed from allowed government domains.
- Small-model answer/auditor behavior is stochastic. The deterministic audit guard prevents citation issues from being treated as valid, but some otherwise useful responses will conservatively require human review.
- A full destructive restore remains unverified until an isolated clean-stack or approved maintenance window is available.
