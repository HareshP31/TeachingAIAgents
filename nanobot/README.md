# nanobot (Task Execution Agent)

Not vendored here — pulled from nanobot's own repo per its install instructions
(see `docs/project-architecture-plan.md` section 11) and run as a sandboxed
subprocess/container.

Only capability: fetch web content, and scoped file I/O in a write-only staging
directory. No direct model access — LangGraph's Researcher node feeds it
instructions and reads its output. See sections 3-4 for the node contract and
section 5 for the Docker sandbox-isolation rationale.

## Tests

The adapter in `app.py` is covered by offline unit tests (no LM Studio, network or
real `nanobot` binary needed). From the repo root, using the built image:

```bash
MSYS_NO_PATHCONV=1 docker run --rm --user root -v "$(pwd -W)/nanobot:/app" -w /app \
  --entrypoint sh teachingaiagents-nanobot \
  -c "pip install -q -r requirements-dev.txt && python -m pytest -p no:cacheprovider"
```

(`pwd -W` is Git Bash on Windows; use `$(pwd)` elsewhere.) Or `pip install -r requirements-dev.txt && pytest` inside `nanobot/` with Python 3.11.
