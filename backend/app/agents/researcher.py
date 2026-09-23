from __future__ import annotations

from app.schemas import AuditResult, ConversationState
from app.services.research import ResearchClient


class Researcher:
    def __init__(self, client: ResearchClient) -> None:
        self.client = client

    async def run(self, state: ConversationState) -> dict:
        audit = AuditResult.model_validate(state["audit"]) if state.get("audit") else None
        response = await self.client.research(
            state["run_id"], state["question"], state.get("research_findings"), audit,
        )
        return {"research_findings": [item.model_dump(mode="json") for item in response.findings]}
