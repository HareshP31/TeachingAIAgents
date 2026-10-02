from __future__ import annotations

# Rough share of wall-clock time each ingestion stage takes on CPU embeddings;
# embedding dominates, so it carries most of the bar.
_STAGES: dict[str, tuple[int, int]] = {
    "queued": (0, 0),
    "downloading": (0, 5),
    "parsing": (5, 15),
    "ocr": (5, 15),
    "chunking": (15, 20),
    "embedding": (20, 95),
    "storing": (95, 100),
    "ready": (100, 100),
}


def progress_percent(stage: str | None, done: int | None, total: int | None) -> int:
    """Overall 0-100 completion for an ingestion stage with optional done/total."""
    if not stage or stage not in _STAGES:
        return 0
    start, end = _STAGES[stage]
    if stage == "ready":
        return 100
    if not total:
        return start
    fraction = min(max((done or 0) / total, 0.0), 1.0)
    return round(start + (end - start) * fraction)


def progress_label(stage: str | None, done: int | None, total: int | None) -> str:
    if stage == "embedding" and total:
        return f"embedding {done or 0}/{total} chunks"
    return {
        "queued": "queued", "downloading": "downloading", "parsing": "reading pages",
        "ocr": "running OCR", "chunking": "chunking text", "storing": "saving to the database",
        "ready": "ready",
    }.get(stage or "", stage or "queued")
