from __future__ import annotations

from typing import Any, Literal

from langgraph.checkpoint.memory import InMemorySaver
from langgraph.graph import END, START, StateGraph
from langgraph.types import Command, interrupt

from app.agents.analyst import Analyst
from app.agents.auditor import Auditor
from app.agents.researcher import Researcher
from app.config import Settings
from app.db.repository import Repository
from app.schemas import AuditResult, CitationIssue, ConversationState, ReviewDecision
from app.services.risk import calculate_risk


_RESEARCH_TERMS = {
    "recent", "latest", "current", "today", "vendor", "contract", "award", "market",
    "sam.gov", "usaspending", "space force", "cloud one", "solicitation",
}


class ConversationGraph:
    def __init__(
        self, repository: Repository, researcher: Researcher, analyst: Analyst,
        auditor: Auditor, settings: Settings, checkpointer: Any | None = None,
    ) -> None:
        self.repository = repository
        self.researcher = researcher
        self.analyst = analyst
        self.auditor = auditor
        self.settings = settings
        builder = StateGraph(ConversationState)
        builder.add_node("route", self._route)
        builder.add_node("researcher", self._researcher)
        builder.add_node("analyst", self._analyst)
        builder.add_node("auditor", self._auditor)
        builder.add_node("human_review", self._human_review)
        builder.add_node("notify", self._notify)
        builder.add_edge(START, "route")
        builder.add_conditional_edges("route", self._after_route, {
            "researcher": "researcher", "analyst": "analyst",
        })
        builder.add_edge("researcher", "analyst")
        builder.add_edge("analyst", "auditor")
        builder.add_conditional_edges("auditor", self._after_auditor, {
            "researcher": "researcher", "human_review": "human_review", "notify": "notify",
        })
        builder.add_conditional_edges("human_review", self._after_review, {
            "researcher": "researcher", "notify": "notify",
        })
        builder.add_edge("notify", END)
        self.graph = builder.compile(checkpointer=checkpointer or InMemorySaver())

    @staticmethod
    def config(thread_id: str) -> dict:
        return {"configurable": {"thread_id": thread_id}}

    async def start(self, state: ConversationState) -> dict:
        await self.repository.update_run(state["run_id"], status="running")
        try:
            return await self.graph.ainvoke(state, config=self.config(state["thread_id"]))
        except Exception as exc:
            await self.repository.update_run(
                state["run_id"], status="failed", error_code="graph_error", error_message=str(exc)[:500],
            )
            await self.repository.log_node(
                state["run_id"], "Error", "Run failed safely", status="failed",
                details={"error": str(exc)[:300]},
            )
            raise

    async def resume(self, thread_id: str, decision: ReviewDecision) -> dict:
        return await self.graph.ainvoke(
            Command(resume=decision.model_dump()), config=self.config(thread_id),
        )

    async def _route(self, state: ConversationState) -> dict:
        normalized = state["question"].lower()
        matches = sorted(term for term in _RESEARCH_TERMS if term in normalized)
        route: Literal["research", "analyst"] = "research" if matches else "analyst"
        reason = f"matched freshness/market terms: {', '.join(matches)}" if matches else "guidebook-first default"
        await self.repository.update_run(state["run_id"], route=route, route_reason=reason)
        await self.repository.log_node(state["run_id"], "Route", reason)
        return {"route": route, "route_reason": reason, "revision_count": 0}

    @staticmethod
    def _after_route(state: ConversationState) -> str:
        return "researcher" if state["route"] == "research" else "analyst"

    async def _researcher(self, state: ConversationState) -> dict:
        result = await self.researcher.run(state)
        await self.repository.update_run(
            state["run_id"], used_researcher=True, research_findings=result["research_findings"],
        )
        await self.repository.log_node(
            state["run_id"], "Researcher", f"Collected {len(result['research_findings'])} sourced findings",
        )
        return result

    async def _analyst(self, state: ConversationState) -> dict:
        result = await self.analyst.run(state)
        await self.repository.update_run(state["run_id"], draft=result["draft"])
        await self.repository.log_node(
            state["run_id"], "Analyst", f"Drafted answer from {len(result['retrieved_chunks'])} guidebook chunks",
        )
        return result

    async def _auditor(self, state: ConversationState) -> dict:
        audit = await self.auditor.run(state)
        next_revision = state.get("revision_count", 0) + (0 if audit.is_valid else 1)
        forced = not audit.is_valid and next_revision >= self.settings.max_revisions
        research_text = " ".join(str(item.get("excerpt", "")) for item in state.get("research_findings", []))
        risk = calculate_risk(
            audit, state.get("draft", ""), research_text, bool(state.get("research_findings")),
            self.settings.materiality_threshold, forced=forced,
        )
        always_review = await self.repository.always_review()
        needs_review = forced or audit.is_valid and (risk.total >= self.settings.risk_threshold or always_review)
        await self.repository.update_run(
            state["run_id"], risk_score=risk.total, risk_breakdown=risk.model_dump(),
            risk_flags=[flag.value for flag in audit.risk_flags],
            citation_issues=[item.model_dump() for item in audit.citation_issues],
            revision_count=next_revision,
        )
        verdict = "approved" if audit.is_valid else "rejected"
        await self.repository.log_node(
            state["run_id"], "Auditor", f"{verdict}; risk score {risk.total}",
            details={"risk_flags": [f.value for f in audit.risk_flags], "forced": forced},
        )
        return {
            "audit": audit.model_dump(mode="json"), "risk_breakdown": risk.model_dump(),
            "revision_count": next_revision, "needs_review": needs_review,
        }

    def _after_auditor(self, state: ConversationState) -> str:
        audit = AuditResult.model_validate(state["audit"])
        if not audit.is_valid and state.get("revision_count", 0) < self.settings.max_revisions:
            return "researcher"
        if state.get("needs_review") or not audit.is_valid:
            return "human_review"
        return "notify"

    async def _human_review(self, state: ConversationState) -> dict:
        await self.repository.update_run(
            state["run_id"], status="awaiting_review", review_status="pending",
        )
        await self.repository.log_node_once(
            state["run_id"], "HumanReview", "awaiting", "Waiting for Slack approval",
        )
        raw = interrupt({
            "run_id": state["run_id"], "draft": state.get("draft", ""),
            "risk_breakdown": state.get("risk_breakdown", {}), "audit": state.get("audit", {}),
        })
        decision = ReviewDecision.model_validate(raw)
        await self.repository.update_run(
            state["run_id"], status="running",
            review_status="approved" if decision.approved else "rejected",
        )
        await self.repository.log_node(
            state["run_id"], "HumanReview", "Human approved" if decision.approved else "Human rejected",
            details={"reviewer_id": decision.reviewer_id, "note": decision.note},
        )
        if not decision.approved:
            audit = AuditResult.model_validate(state["audit"])
            audit.is_valid = False
            audit.citation_issues.append(CitationIssue(
                citation="human_review", reason=decision.note or "Human reviewer requested revision",
            ))
            return {"review": decision.model_dump(), "audit": audit.model_dump(mode="json")}
        return {"review": decision.model_dump()}

    @staticmethod
    def _after_review(state: ConversationState) -> str:
        return "notify" if state.get("review", {}).get("approved") else "researcher"

    async def _notify(self, state: ConversationState) -> dict:
        answer = state.get("draft", "")
        await self.repository.update_run(
            state["run_id"], status="completed", final_answer=answer,
            review_status=state.get("review", {}).get("approved") and "approved" or "auto_approved",
        )
        await self.repository.log_node(state["run_id"], "Notify", "Final answer ready for Slack")
        return {"final_answer": answer}
