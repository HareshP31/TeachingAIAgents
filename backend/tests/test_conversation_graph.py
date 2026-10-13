from __future__ import annotations

from typing import Any
from uuid import uuid4

import pytest

from app.agents.analyst import Analyst
from app.agents.auditor import Auditor
from app.agents.researcher import Researcher
from app.config import Settings
from app.graphs.conversation_graph import ConversationGraph
from app.schemas import ConversationState, ReviewDecision
from app.services.embeddings import FakeEmbedder
from app.services.research import ResearchClient
from app.services.scope_gate import DECLINE_MESSAGE, ScopeGate
from app.slack.bolt_app import interrupt_payload


class MemoryRepository:
    def __init__(self) -> None:
        self.run: dict[str, Any] = {}
        self.logs: list[dict[str, Any]] = []
        self.documents: list[dict[str, Any]] = []
        self.searched_with: list[list[str] | None] = []
        self.index_channels: list[str | None] = []

    async def update_run(self, run_id, **fields):
        self.run.update(fields)

    async def log_node(self, run_id, node, summary, status="completed", details=None):
        self.logs.append({"node": node, "summary": summary, "status": status, "details": details or {}})

    async def log_node_once(self, run_id, node, status, summary):
        if not any(row["node"] == node and row["status"] == status for row in self.logs):
            await self.log_node(run_id, node, summary, status)

    async def always_review(self):
        return False

    async def document_index(self, channel_id=None):
        self.index_channels.append(channel_id)
        return self.documents

    async def search_chunks(self, embedding, limit=8, *, include_historical=False, document_ids=None):
        self.searched_with.append(document_ids)
        return [{"text": "Cloud acquisition guidance", "page_start": 1, "page_end": 1,
                 "filename": "Cloud Acquisition Guidebook.pdf", "score": 0.9}]


def graph_fixture() -> tuple[ConversationGraph, MemoryRepository]:
    # app_mode="test" + FakeEmbedder + fake=True below: deterministic,
    # no LM Studio/Qwen and no real BGE embeddings, so this fixture never
    # touches the real local Qwen setup - that's the point, for fast/offline
    # unit tests, not a reflection of production (local/live) behavior.
    settings = Settings(app_mode="test", database_url="postgresql://unused")
    repository = MemoryRepository()
    embedder = FakeEmbedder()
    graph = ConversationGraph(
        repository, Researcher(ResearchClient("http://unused", 1, fake=True)),
        Analyst(repository, embedder, settings, None, True), Auditor(None, True), settings,
    )
    return graph, repository


def state(question: str) -> ConversationState:
    run_id = str(uuid4())
    return {
        "run_id": run_id, "thread_id": f"test:{run_id}", "channel_id": "test",
        "requester_id": "tester", "question": question,
    }


@pytest.mark.asyncio
async def test_guidebook_route_skips_research_and_auto_approves() -> None:
    graph, repository = graph_fixture()
    result = await graph.start(state("Which acquisition pathway applies to commercial cloud hosting?"))
    assert result["route"] == "analyst"
    assert result["final_answer"]
    assert repository.run["status"] == "completed"
    assert "Researcher" not in [row["node"] for row in repository.logs]


@pytest.mark.asyncio
async def test_market_route_revises_interrupts_and_resumes() -> None:
    graph, repository = graph_fixture()
    initial = state("What vendors have recent Space Force contracts under Cloud One?")
    result = await graph.start(initial)
    payload = interrupt_payload(result)
    assert payload is not None
    assert payload["risk_breakdown"]["total"] == 75
    assert result["revision_count"] == 1
    assert [row["node"] for row in repository.logs].count("Researcher") == 2
    resumed = await graph.resume(initial["thread_id"], ReviewDecision(
        approved=True, reviewer_id="reviewer",
    ))
    assert resumed["final_answer"]
    assert repository.run["status"] == "completed"


@pytest.mark.asyncio
async def test_scoped_question_skips_web_research_and_filters_retrieval() -> None:
    graph, repository = graph_fixture()
    repository.documents = [{
        "id": "doc-1", "filename": "Acme Program Plan.pdf", "nickname": "acme plan",
        "is_canonical": True, "channel_linked_at": None, "last_uploaded_at": None, "created_at": 1,
    }]
    # "vendor" and "contract" would normally trigger web research.
    result = await graph.start(state("What does the acme plan say about vendor contract risk?"))
    assert result["route"] == "analyst"
    assert result["document_ids"] == ["doc-1"]
    assert result["scope_label"] == "acme plan"
    assert repository.searched_with == [["doc-1"]]
    # the asking channel is passed along so "just uploaded" can prefer its uploads
    assert repository.index_channels == ["test"]
    assert "Researcher" not in [row["node"] for row in repository.logs]
    route_log = next(row for row in repository.logs if row["node"] == "Route")
    assert "scoped to acme plan" in route_log["summary"]


@pytest.mark.asyncio
async def test_unscoped_question_still_searches_everything() -> None:
    graph, repository = graph_fixture()
    await graph.start(state("Which acquisition pathway applies to commercial cloud hosting?"))
    assert repository.searched_with == [None]


class StubLLM:
    """Stands in for LMStudioClient.chat_json in the scope classifier."""

    def __init__(self, result: dict | Exception) -> None:
        self.result = result
        self.calls = 0

    async def chat_json(self, messages, schema, **kwargs):
        self.calls += 1
        if isinstance(self.result, Exception):
            raise self.result
        return self.result


def gated_graph(gate: ScopeGate | None = None) -> tuple[ConversationGraph, MemoryRepository]:
    graph, repository = graph_fixture()
    graph = ConversationGraph(
        repository, graph.researcher, graph.analyst, graph.auditor, graph.settings,
        scope_gate=gate or ScopeGate(None, True),
    )
    return graph, repository


def nodes(repository: MemoryRepository) -> list[str]:
    return [row["node"] for row in repository.logs]


@pytest.mark.asyncio
async def test_off_topic_question_is_declined_before_anything_else_runs() -> None:
    graph, repository = gated_graph()
    result = await graph.start(state("What are the winning lottery numbers?"))
    assert result["final_answer"] == DECLINE_MESSAGE
    assert repository.run["status"] == "declined"
    assert repository.run["route"] == "declined"
    assert repository.run["final_answer"] == DECLINE_MESSAGE
    assert repository.run["route_reason"].startswith("out of scope:")
    # Only the gate and the decline are recorded: no routing, retrieval, drafting or audit.
    assert nodes(repository) == ["ScopeGate", "Decline"]
    assert repository.searched_with == []
    assert "risk_score" not in repository.run
    assert repository.logs[0]["summary"].startswith("out_of_scope:")


@pytest.mark.asyncio
async def test_in_scope_question_runs_the_unchanged_pipeline_after_the_gate() -> None:
    graph, repository = gated_graph()
    result = await graph.start(state("Which acquisition pathway applies to commercial cloud hosting?"))
    assert result["route"] == "analyst"
    assert repository.run["status"] == "completed"
    assert nodes(repository) == ["ScopeGate", "Route", "Analyst", "Auditor", "Notify"]
    assert repository.logs[0]["summary"].startswith("in_scope:")


@pytest.mark.asyncio
async def test_market_run_still_interrupts_and_resumes_behind_the_gate() -> None:
    graph, repository = gated_graph()
    initial = state("What vendors have recent Space Force contracts under Cloud One?")
    result = await graph.start(initial)
    assert interrupt_payload(result) is not None
    assert nodes(repository).count("ScopeGate") == 1
    resumed = await graph.resume(initial["thread_id"], ReviewDecision(approved=True, reviewer_id="r"))
    assert resumed["final_answer"]
    assert repository.run["status"] == "completed"
    # Resuming a paused run must not send it back through the gate.
    assert nodes(repository).count("ScopeGate") == 1


@pytest.mark.asyncio
async def test_question_about_a_document_skips_the_classifier() -> None:
    llm = StubLLM({"verdict": "out_of_scope", "reason": "unrelated"})
    graph, repository = gated_graph(ScopeGate(llm, False))
    repository.documents = [{
        "id": "doc-1", "filename": "Acme Program Plan.pdf", "nickname": "acme plan",
        "is_canonical": True, "channel_linked_at": None, "last_uploaded_at": None, "created_at": 1,
    }]
    await graph.start(state("What does the acme plan say about lottery numbers?"))
    assert llm.calls == 0
    assert repository.run["status"] == "completed"
    assert "classifier skipped" in repository.logs[0]["summary"]


@pytest.mark.asyncio
async def test_unclear_verdict_is_let_through() -> None:
    llm = StubLLM({"verdict": "unclear", "reason": "too short to tell"})
    graph, repository = gated_graph(ScopeGate(llm, False))
    await graph.start(state("What are the key risks?"))
    assert llm.calls == 1
    assert repository.run["status"] == "completed"
    assert repository.logs[0]["summary"] == "unclear: too short to tell"


@pytest.mark.asyncio
async def test_classifier_failure_fails_open() -> None:
    graph, repository = gated_graph(ScopeGate(StubLLM(RuntimeError("LM Studio down")), False))
    await graph.start(state("Which acquisition pathway applies to commercial cloud hosting?"))
    assert repository.run["status"] == "completed"
    assert repository.logs[0]["summary"].startswith("unclear:")


@pytest.mark.asyncio
async def test_confident_llm_refusal_declines_the_run() -> None:
    llm = StubLLM({"verdict": "out_of_scope", "reason": "banana bread is not acquisition"})
    graph, repository = gated_graph(ScopeGate(llm, False))
    await graph.start(state("Give me a recipe for banana bread"))
    assert repository.run["status"] == "declined"
    assert nodes(repository) == ["ScopeGate", "Decline"]
    assert repository.logs[0]["details"]["reason"] == "banana bread is not acquisition"
