from __future__ import annotations

import pytest

from app.config import Settings
from app.services.embeddings import FakeEmbedder
from app.services.evaluation import CITATION, CorpusEvaluator


class EvaluationRepository:
    async def search_chunks(self, embedding, limit=5, *, include_historical=False):
        return [{
            "filename": "Guide.pdf", "page_start": 2, "page_end": 2,
            "text": "grounded text", "score": 0.9,
        }]


@pytest.mark.asyncio
async def test_retrieval_evaluation_reports_source_hit(tmp_path) -> None:
    cases = tmp_path / "cases.yaml"
    cases.write_text("""cases:
  - id: grounded
    question: What is the rule?
    expected_sources: [Guide.pdf]
  - id: absent
    question: What is missing?
    expected_sources: []
    expected_behavior: insufficient
""")
    evaluator = CorpusEvaluator(
        EvaluationRepository(), FakeEmbedder(), Settings(app_mode="test"),
    )
    report = await evaluator.run(cases)
    assert report["case_count"] == 2
    assert report["source_hit_rate"] == 1


def test_citation_pattern_accepts_filenames_with_commas() -> None:
    assert CITATION.findall("[Guidebook, Office of DoD CIO, Jan2024.pdf, p. 12]") == [
        ("Guidebook, Office of DoD CIO, Jan2024.pdf", "12")
    ]
