# nanobot (Task Execution Agent)

Not vendored here — pulled from nanobot's own repo per its install instructions
(see `docs/project-architecture-plan.md` section 11) and run as a sandboxed
subprocess/container.

Only capability: fetch web content, and scoped file I/O in a write-only staging
directory. No direct model access — LangGraph's Researcher node feeds it
instructions and reads its output. See sections 3-4 for the node contract and
section 5 for the Docker sandbox-isolation rationale.
