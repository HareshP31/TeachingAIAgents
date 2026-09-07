"""Postgres + pgvector schema: document chunks, embeddings, LangGraph checkpoints
(including paused HumanReview state), and run telemetry (the {node, timestamp,
summary} log every graph node appends to — the dashboard's only data source).
See docs/project-architecture-plan.md sections 3-4.
"""

# TODO: define tables (documents, chunks w/ pgvector embedding column,
# graph_runs, run_events) with asyncpg or an ORM of choice.
