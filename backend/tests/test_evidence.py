from app.services.evidence import compact_guidebook_chunks, compact_research_findings


def test_compact_chunks_preserves_citation_coordinates_and_bounds_text() -> None:
    result = compact_guidebook_chunks([{
        "id": "ignored", "filename": "guide.pdf", "page_start": 4,
        "page_end": 5, "score": 0.9, "text": "x" * 900,
    }])
    assert result == [{
        "filename": "guide.pdf", "page_start": 4, "page_end": 5,
        "score": 0.9, "text": "x" * 700,
    }]


def test_compact_research_preserves_provenance_and_bounds_excerpt() -> None:
    result = compact_research_findings([{
        "title": "source", "url": "https://sam.gov/example", "excerpt": "x" * 700,
        "content_sha256": "abc", "snippet_only": False, "ignored": "large",
    }])
    assert result == [{
        "title": "source", "url": "https://sam.gov/example",
        "content_sha256": "abc", "snippet_only": False, "excerpt": "x" * 500,
    }]
