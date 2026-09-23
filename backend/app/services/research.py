from __future__ import annotations

from datetime import UTC, datetime
from uuid import UUID

import httpx

from app.schemas import AuditResult, ResearchFinding, ResearchRequest, ResearchResponse


ALLOWED_RESEARCH_DOMAINS = [
    "sam.gov", "usaspending.gov", "spacewerx.us", "afwerx.com", "gsa.gov",
    "dau.edu", "acquisition.gov", "esd.whs.mil",
]


class ResearchClient:
    def __init__(self, url: str, timeout: float, fake: bool = False) -> None:
        self.url = url.rstrip("/")
        self.timeout = timeout
        self.fake = fake

    async def research(
        self, run_id: str, query: str, prior: list[dict] | None = None,
        audit: AuditResult | None = None,
    ) -> ResearchResponse:
        if self.fake:
            finding = ResearchFinding(
                title="Cloud One continuation contract",
                url="https://www.usaspending.gov/award/CONT_AWD_FA872624F0001_9700_47QTCK18D0001_4732",
                excerpt=("SAIC received a Cloud One continuation contract valued at approximately "
                         "$382.7M. The acquisition should account for vendor lock-in and consumption costs."),
                retrieved_at=datetime.now(UTC),
                source_mode="fake", fetched_at=datetime.now(UTC),
                content_sha256="fake", http_status=200, snippet_only=False,
            )
            return ResearchResponse(findings=[finding], summary=finding.excerpt, live=False)
        payload = ResearchRequest(
            run_id=UUID(run_id), query=query,
            prior_findings=[ResearchFinding.model_validate(item) for item in prior or []],
            audit_feedback=audit, allowed_domains=ALLOWED_RESEARCH_DOMAINS,
        )
        async with httpx.AsyncClient(timeout=self.timeout) as client:
            response = await client.post(f"{self.url}/research", json=payload.model_dump(mode="json"))
            response.raise_for_status()
            return ResearchResponse.model_validate(response.json())

    async def healthy(self) -> bool:
        if self.fake:
            return True
        try:
            async with httpx.AsyncClient(timeout=3) as client:
                response = await client.get(f"{self.url}/health")
                return response.is_success
        except Exception:
            return False
