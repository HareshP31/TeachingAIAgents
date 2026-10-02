"""Work out whether a question is about one specific document.

Resolution order (first hit wins):
1. A nickname mentioned in the question.
2. "the one I just uploaded" style phrases -> the newest upload in the asking
   channel, else the newest upload anywhere.
3. A conservative filename match: the question must reference a document
   ("guidebook", "pdf"...) and contain most of the title's distinctive words.
   A passing mention of "risk" or "cloud" never locks onto a single document.
"""
from __future__ import annotations

import math
import re
from dataclasses import dataclass
from typing import Any


_HISTORICAL = re.compile(
    r"\b(historical|prior|previous|superseded|version\s+\d|(?:19|20)\d{2})\b", re.IGNORECASE,
)
_LATEST_UPLOAD = re.compile(
    r"\b(?:(?:just|recently|newly|last)\s+(?:uploaded|added|dropped|shared)"
    r"|(?:latest|newest|most\s+recent)\s+(?:upload(?:ed)?|document|doc|file|pdf)"
    r"|(?:this|that|the|my)\s+(?:uploaded\s+)?(?:document|doc|file|pdf)"
    r"|uploaded\s+(?:document|doc|file|pdf))\b",
    re.IGNORECASE,
)
_STOPWORDS = {
    "the", "of", "and", "in", "to", "for", "a", "an", "on", "pdf", "vol", "volume",
    "guide", "guidebook", "guidance",
}
_MONTHS = "jan|feb|mar|apr|may|jun|jul|aug|sep|sept|oct|nov|dec"
_NOISE = re.compile(
    rf"^(?:v?\d+(?:\.\d+)*|\d{{1,2}}(?:{_MONTHS})\d{{0,4}}|(?:{_MONTHS})\d{{2,4}}|(?:19|20)\d{{2}}|\d)$",
)
# Words common to most titles say nothing about *which* document is meant.
_MAX_DOC_FREQUENCY = 0.15
_MIN_COVERAGE = 0.5
# Filename matching only applies when the question clearly refers to a document.
_DOC_CUE = re.compile(r"\b(?:guidebook|guide|handbook|document|doc|pdf|manual|primer)s?\b", re.IGNORECASE)


def wants_historical(question: str) -> bool:
    return bool(_HISTORICAL.search(question))


def _stem(token: str) -> str:
    return token[:-1] if len(token) > 3 and token.endswith("s") else token


def _tokens(text: str) -> list[str]:
    return [_stem(item) for item in re.findall(r"[a-z0-9]+", text.lower())]


def _title_tokens(filename: str) -> set[str]:
    stem = re.sub(r"\.pdf$", "", filename, flags=re.IGNORECASE)
    kept = set()
    for raw in re.findall(r"[a-z0-9]+", stem.lower()):
        if raw in _STOPWORDS or _NOISE.match(raw) or len(raw) < 2:
            continue
        kept.add(_stem(raw))
    return kept


@dataclass(frozen=True)
class DocumentScope:
    document_ids: list[str]
    label: str
    reason: str  # "nickname" | "latest_upload" | "filename"


def _label(documents: list[dict[str, Any]]) -> str:
    names = [item.get("nickname") or item["filename"] for item in documents]
    return names[0] if len(names) == 1 else f"{len(names)} documents: " + "; ".join(names[:3])


def _make(documents: list[dict[str, Any]], reason: str) -> DocumentScope:
    return DocumentScope([str(item["id"]) for item in documents], _label(documents), reason)


def _latest_upload(documents: list[dict[str, Any]]) -> dict[str, Any] | None:
    # Prefer the newest upload in the asking channel; in a channel with no uploads
    # fall back to the newest upload anywhere. Imported-only documents never count.
    here = [item for item in documents if item.get("channel_linked_at")]
    if here:
        return max(here, key=lambda item: item["channel_linked_at"])
    anywhere = [item for item in documents if item.get("last_uploaded_at")]
    return max(anywhere, key=lambda item: item["last_uploaded_at"]) if anywhere else None


def resolve_scope(
    question: str, documents: list[dict[str, Any]], *, include_historical: bool | None = None,
) -> DocumentScope | None:
    """`documents` are the ready documents (see Repository.document_index): id,
    filename, nickname, is_canonical, channel_linked_at (last upload in the asking
    channel) and last_uploaded_at (last upload in any channel)."""
    if include_historical is None:
        include_historical = wants_historical(question)
    candidates = [item for item in documents if include_historical or item.get("is_canonical", True)]
    if not candidates:
        return None
    question_tokens = _tokens(question)
    question_set = set(question_tokens)
    padded = " " + " ".join(question_tokens) + " "

    named = []
    for item in candidates:
        nickname = item.get("nickname")
        if nickname and f" {' '.join(_tokens(nickname))} " in padded:
            named.append(item)
    if named:
        longest = max(len(item["nickname"]) for item in named)
        return _make([item for item in named if len(item["nickname"]) == longest], "nickname")

    if _LATEST_UPLOAD.search(question):
        latest = _latest_upload(candidates)
        if latest:
            return _make([latest], "latest_upload")

    if not _DOC_CUE.search(question):
        # Topical questions ("how does systems engineering work?") must search
        # everything; only an explicit reference to a document narrows the search.
        return None

    frequency: dict[str, int] = {}
    titles = {str(item["id"]): _title_tokens(item["filename"]) for item in candidates}
    for tokens in titles.values():
        for token in tokens:
            frequency[token] = frequency.get(token, 0) + 1
    limit = max(1, math.floor(_MAX_DOC_FREQUENCY * len(candidates)))
    scored: list[tuple[float, dict[str, Any]]] = []
    for item in candidates:
        distinctive = {token for token in titles[str(item["id"])] if frequency[token] <= limit}
        if not distinctive:
            continue
        matched = distinctive & question_set
        coverage = len(matched) / len(distinctive)
        if len(matched) >= min(2, len(distinctive)) and coverage >= _MIN_COVERAGE:
            scored.append((coverage + len(matched) / 100, item))
    if not scored:
        return None
    best = max(score for score, _ in scored)
    return _make([item for score, item in scored if score == best], "filename")
