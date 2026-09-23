from __future__ import annotations

import logging
from contextlib import asynccontextmanager
from uuid import uuid4

from fastapi import FastAPI, HTTPException, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from langgraph.checkpoint.postgres.aio import AsyncPostgresSaver
from pydantic import BaseModel

from app.agents.analyst import Analyst
from app.agents.auditor import Auditor
from app.agents.researcher import Researcher
from app.config import get_settings
from app.db.database import Database
from app.db.migrations import migrate
from app.db.repository import Repository
from app.graphs.conversation_graph import ConversationGraph
from app.graphs.ingestion_graph import IngestionService
from app.schemas import ConversationState, ReviewDecision
from app.services.embeddings import FakeEmbedder, SentenceTransformerEmbedder
from app.services.llm import LMStudioClient
from app.services.research import ResearchClient
from app.slack.bolt_app import SlackRuntime, interrupt_payload


logger = logging.getLogger(__name__)
settings = get_settings()


@asynccontextmanager
async def lifespan(app: FastAPI):
    logging.basicConfig(level=settings.log_level)
    problems = settings.validate_live()
    if problems:
        raise RuntimeError("; ".join(problems))
    database = Database(settings.database_url)
    await database.open()
    await migrate(database)
    repository = Repository(database)
    fake = settings.app_mode in {"fake", "test"}
    embedder = FakeEmbedder(settings.embedding_dimensions) if fake else SentenceTransformerEmbedder(settings.embedding_model)
    llm = None if fake else LMStudioClient(
        settings.lm_studio_base_url, settings.lm_studio_api_key, settings.lm_studio_model,
    )
    research_client = ResearchClient(settings.nanobot_url, settings.nanobot_timeout_seconds, fake=fake)
    checkpoint_context = AsyncPostgresSaver.from_conn_string(settings.database_url)
    checkpointer = await checkpoint_context.__aenter__()
    await checkpointer.setup()
    graph = ConversationGraph(
        repository, Researcher(research_client),
        Analyst(repository, embedder, settings, llm, fake), Auditor(llm, fake),
        settings, checkpointer,
    )
    ingestion = IngestionService(repository, embedder, settings)
    slack: SlackRuntime | None = None
    if settings.slack_enabled:
        slack = SlackRuntime(settings, repository, graph, ingestion)
        await slack.start()
    app.state.database = database
    app.state.repository = repository
    app.state.graph = graph
    app.state.ingestion = ingestion
    app.state.research_client = research_client
    app.state.llm = llm
    app.state.slack = slack
    try:
        yield
    finally:
        if slack:
            await slack.stop()
        await checkpoint_context.__aexit__(None, None, None)
        await database.close()


app = FastAPI(title="Teaching AI Agents Backend", version="0.1.0", lifespan=lifespan)
app.add_middleware(
    CORSMiddleware,
    allow_origins=[settings.frontend_origin],
    allow_credentials=False,
    allow_methods=["GET", "POST"],
    allow_headers=["Content-Type"],
)


@app.exception_handler(Exception)
async def unexpected_error(request: Request, exc: Exception) -> JSONResponse:
    logger.exception("Unhandled request failure", exc_info=exc)
    return JSONResponse(
        status_code=500,
        content={"error": {"code": "internal_error", "message": "Request failed safely"}},
    )


@app.get("/")
async def root() -> dict:
    return {"name": app.title, "version": app.version, "mode": settings.app_mode}


@app.get("/health")
@app.get("/health/live")
async def health() -> dict:
    return {"status": "ok"}


@app.get("/health/ready")
async def ready(request: Request) -> dict:
    postgres = await request.app.state.database.ping()
    nanobot = await request.app.state.research_client.healthy()
    lm_studio = True if request.app.state.llm is None else await request.app.state.llm.healthy()
    slack = not settings.slack_enabled or request.app.state.slack is not None
    checks = {"postgres": postgres, "nanobot": nanobot, "lm_studio": lm_studio, "slack": slack}
    return {"status": "ready" if all(checks.values()) else "degraded", "mode": settings.app_mode, "checks": checks}


@app.get("/api/overview")
async def overview(request: Request) -> dict:
    repository: Repository = request.app.state.repository
    return {
        "mode": settings.app_mode,
        "always_review": await repository.always_review(),
        "imports": await repository.list_corpus_imports(5),
        "documents": await repository.list_documents(8),
        "runs": await repository.list_runs(25),
    }


@app.get("/api/documents")
async def documents(request: Request, limit: int = 100) -> list[dict]:
    return await request.app.state.repository.list_documents(min(max(limit, 1), 200))


@app.get("/api/runs")
async def runs(request: Request, limit: int = 25, status: str | None = None) -> list[dict]:
    return await request.app.state.repository.list_runs(min(max(limit, 1), 100), status)


@app.get("/api/runs/{run_id}")
async def run_detail(run_id: str, request: Request) -> dict:
    run = await request.app.state.repository.get_run(run_id)
    if run is None:
        raise HTTPException(404, "Run not found")
    return run


@app.get("/api/settings")
async def public_settings(request: Request) -> dict:
    return {
        "always_review": await request.app.state.repository.always_review(),
        "risk_threshold": settings.risk_threshold,
        "materiality_threshold": settings.materiality_threshold,
        "max_revisions": settings.max_revisions,
    }


class DevRunRequest(BaseModel):
    question: str


class DevReviewRequest(BaseModel):
    approved: bool = True
    note: str | None = None


def _require_dev() -> None:
    if settings.app_mode == "live":
        raise HTTPException(404, "Not found")


@app.post("/api/dev/runs")
async def create_dev_run(body: DevRunRequest, request: Request) -> dict:
    _require_dev()
    source_id = f"dev:{uuid4()}"
    thread_id = source_id
    run_id = await request.app.state.repository.create_run(
        source_event_id=source_id, thread_id=thread_id, channel_id="dev",
        requester_id="developer", question=body.question,
    )
    state: ConversationState = {
        "run_id": str(run_id), "thread_id": thread_id, "channel_id": "dev",
        "requester_id": "developer", "question": body.question,
    }
    try:
        result = await request.app.state.graph.start(state)
    except Exception as exc:
        logger.exception("Workflow failed", exc_info=exc)
        await request.app.state.repository.update_run(
            run_id, status="failed", error_code="workflow_dependency_failure",
            error_message=f"{type(exc).__name__}: {exc}"[:500],
        )
        raise HTTPException(
            503, detail={"code": "workflow_dependency_failure", "message": "Workflow dependency failed"},
        ) from exc
    return {"run": await request.app.state.repository.get_run(run_id), "interrupted": bool(interrupt_payload(result))}


@app.post("/api/dev/runs/{run_id}/review")
async def review_dev_run(run_id: str, body: DevReviewRequest, request: Request) -> dict:
    _require_dev()
    run = await request.app.state.repository.get_run(run_id)
    if not run:
        raise HTTPException(404, "Run not found")
    try:
        result = await request.app.state.graph.resume(run["thread_id"], ReviewDecision(
            approved=body.approved, reviewer_id="developer", note=body.note,
        ))
    except Exception as exc:
        logger.exception("Workflow resume failed", exc_info=exc)
        await request.app.state.repository.update_run(
            run_id, status="failed", error_code="review_resume_failure",
            error_message=f"{type(exc).__name__}: {exc}"[:500],
        )
        raise HTTPException(
            503, detail={"code": "review_resume_failure", "message": "Review resume failed"},
        ) from exc
    return {"run": await request.app.state.repository.get_run(run_id), "interrupted": bool(interrupt_payload(result))}
