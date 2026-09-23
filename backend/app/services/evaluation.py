from __future__ import annotations

import json
import re
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import yaml

from app.agents.analyst import Analyst
from app.agents.auditor import Auditor
from app.config import Settings
from app.db.repository import Repository
from app.services.embeddings import Embedder


CITATION = re.compile(r"\[([^\]]+),\s*p\.\s*(\d+)\]", re.IGNORECASE)


class CorpusEvaluator:
    def __init__(
        self, repository: Repository, embedder: Embedder, settings: Settings,
        analyst: Analyst | None = None, auditor: Auditor | None = None,
    ) -> None:
        self.repository = repository
        self.embedder = embedder
        self.settings = settings
        self.analyst = analyst
        self.auditor = auditor

    async def run(self, cases_path: Path, *, full: bool = False) -> dict[str, Any]:
        payload = yaml.safe_load(cases_path.read_text())
        cases = payload["cases"]
        results = []
        for case in cases:
            vector = (await self.embedder.embed([case["question"]], query=True))[0]
            chunks = await self.repository.search_chunks(
                vector, self.settings.retrieval_limit,
                include_historical=bool(case.get("include_historical")),
            )
            names = list(dict.fromkeys(item["filename"] for item in chunks))
            expected = case.get("expected_sources", [])
            if not expected:
                hit = None
            elif case.get("expected_match") == "all":
                hit = all(name in names for name in expected)
            else:
                hit = any(name in names for name in expected)
            row: dict[str, Any] = {
                "id": case["id"], "question": case["question"],
                "expected_sources": expected, "retrieved_sources": names,
                "source_hit": hit,
            }
            if full:
                if not self.analyst or not self.auditor:
                    raise ValueError("Full evaluation requires Analyst and Auditor")
                state = {"question": case["question"], "research_findings": []}
                analysis = await self.analyst.run(state)
                draft = analysis["draft"]
                audit = await self.auditor.run({**state, **analysis})
                valid_citations = []
                for filename, page in CITATION.findall(draft):
                    page_number = int(page)
                    valid_citations.append(any(
                        item["filename"] == filename
                        and item["page_start"] <= page_number <= item["page_end"]
                        for item in analysis["retrieved_chunks"]
                    ))
                behavior = case.get("expected_behavior", "grounded")
                limitation = bool(re.search(
                    r"\b(insufficient|cannot determine|does not (?:contain|provide|identify|state)|"
                    r"not (?:available|provided|found|possible to determine))\b",
                    draft, re.IGNORECASE,
                ))
                citations_valid = (
                    limitation if behavior == "insufficient"
                    else bool(valid_citations) and all(valid_citations)
                )
                row.update(
                    draft=draft, auditor=audit.model_dump(mode="json"),
                    citation_count=len(valid_citations),
                    citations_valid=citations_valid,
                    behavior_pass=(limitation if behavior == "insufficient" else True),
                )
            results.append(row)
        grounded = [row for row in results if row["source_hit"] is not None]
        report = {
            "generated_at": datetime.now(UTC).isoformat(), "full": full,
            "case_count": len(results),
            "source_hit_rate": (
                sum(bool(row["source_hit"]) for row in grounded) / len(grounded)
                if grounded else 0
            ),
            "results": results,
        }
        if full:
            report["citation_valid_rate"] = sum(
                bool(row.get("citations_valid")) for row in grounded
            ) / len(grounded) if grounded else 0
            report["behavior_pass_rate"] = sum(
                bool(row.get("behavior_pass")) for row in results
            ) / len(results) if results else 0
            report["auditor_valid_rate"] = sum(
                bool(row.get("auditor", {}).get("is_valid")) for row in results
            ) / len(results) if results else 0
        return report


def write_report(report: dict[str, Any], output: Path) -> None:
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(report, indent=2, default=str) + "\n")
