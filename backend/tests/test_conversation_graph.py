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
from app.slack.bolt_app import interrupt_payload


class MemoryRepository:
    def __init__(self) -> None:
        self.run: dict[str, Any] = {}
        self.logs: list[dict[str, Any]] = []

    async def update_run(self, run_id, **fields):
        self.run.update(fields)

    async def log_node(self, run_id, node, summary, status="completed", details=None):
        self.logs.append({"node": node, "summary": summary, "status": status, "details": details or {}})

    async def log_node_once(self, run_id, node, status, summary):
        if not any(row["node"] == node and row["status"] == status for row in self.logs):
            await self.log_node(run_id, node, summary, status)

    async def always_review(self):
        return False

    async def search_chunks(self, embedding, limit=8, *, include_historical=False):
        return [{"text": "Cloud acquisition guidance", "page_start": 1, "page_end": 1,
                 "filename": "Cloud Acquisition Guidebook.pdf", "score": 0.9}]


def graph_fixture() -> tuple[ConversationGraph, MemoryRepository]:
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
