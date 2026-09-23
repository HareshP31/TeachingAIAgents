from __future__ import annotations

from typing import Any


def compact_guidebook_chunks(
    chunks: list[dict[str, Any]], *, text_limit: int = 700,
) -> list[dict[str, Any]]:
    """Keep citation coordinates while bounding the 7B model prompt."""
    compact = []
    for chunk in chunks:
        compact.append({
            "filename": chunk.get("filename"),
            "page_start": chunk.get("page_start"),
            "page_end": chunk.get("page_end"),
            "score": chunk.get("score"),
            "text": str(chunk.get("text", ""))[:text_limit],
        })
    return compact


def compact_research_findings(
    findings: list[dict[str, Any]], *, excerpt_limit: int = 500, limit: int = 4,
) -> list[dict[str, Any]]:
    """Bound web evidence while retaining the provenance the Auditor needs."""
    keep = (
        "title", "url", "source_mode", "retrieved_at", "fetched_at",
        "content_sha256", "http_status", "snippet_only",
    )
    compact = []
    for finding in findings[:limit]:
        row = {key: finding.get(key) for key in keep if key in finding}
        row["excerpt"] = str(finding.get("excerpt", ""))[:excerpt_limit]
        compact.append(row)
    return compact
