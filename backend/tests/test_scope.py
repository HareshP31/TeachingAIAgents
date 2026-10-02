from __future__ import annotations

from datetime import datetime, timedelta

import pytest

from app.services.progress import progress_label, progress_percent
from app.services.scope import resolve_scope, wants_historical

TITLES = [
    "Software Acquisition Strategy -OUSD(A&S) Guidance V1.5 11May20.pdf",
    "DoDI 500080p - Operation of the Middle Tier of Acquisition.pdf",
    "DoDI 500087p - Operation of the Software Acquisition Pathway.pdf",
    "DoD AAF Quick Ref Card --V3.4, 21Oct24.pdf",
    "DoDI 500002p - Operation of the Adaptive Acquisition Framework.pdf",
    "DoD Source Selection Procedures, DFAR Supplement, 20Aug22.pdf",
    "DoD AAF Quick Ref Card --V3.7, 16Sep25.pdf",
    "DoD Agile-101, An Agile Primer, V2.0, 16May23.pdf",
    "DoD Risk, Issue, and Opportunity (RIO) Management Guide, OUSD(R&E), V2.2, Sep2023.pdf",
    "Agile Software Acquisition Guidebook V1.0 27Feb20.pdf",
    "Modernized SAR Prep & Review Guidance, OUSD(A&S) ADA, 22Nov2023.pdf",
    "USSF Requirements Development Guidebook, Vol 1, Cap Dev Overview & Oper Cap Reqts Governance, 01Oct 23.pdf",
    "DAU - Guide to Program Management Knowledge Skills and Practices, V1.2, 18Jul2024.pdf",
    "USSF SSC Command Plan 2026.pdf",
    "Human Systems Integration (HSI) Guidebook, OUSD(R&E), May2022.pdf",
    "DoD Mission Engineering Guide, V2.0, 01Oct23.pdf",
    "Engineering of Defense Systems Guidebook, OUSD(R&E) OSEA - July2024.pdf",
    "Product Support Manager (PSM) Guidebook, OUSD(A&S), May2022.pdf",
    "Systems Engineering Guidebook, OUSD(R&E), Feb2022.pdf",
    "Software Developmental Test and Evaluation in DevSecOps Guidebook, OUSD(R&E), Jan2025.pdf",
    "Requirements for Acquisition of Digital Capabilities Guidebook, Office of DoD CIO, Jan2024.pdf",
    "M&S for T&E Guidebook, May2025.pdf",
    "DAU - Guide to Program Management Business Processes, V2, 17Sep24.pdf",
    "DoD Technology and Program Protection Guidebook, OUSD(R&E), Jul2022.pdf",
    "DAU - DoD Cloud Computing Acquisition Guidebook, V1.2, Nov2019.pdf",
    "Performance-Based Logistics (PBL) Guidebook, OUSD(A&S), Oct2023.pdf",
    "DoD Enterprise DevSecOps Fundamentals V2.5 Oct2024.pdf",
    "Intelligence Support to the AAF (ISTAFF) Guidebook, OUSD(A&S), Sep2023.pdf",
]
BASE = datetime(2026, 9, 1)
CLOUD = 24
AGILE_SOFTWARE = 9


def library(**extra) -> list[dict]:
    rows = [{
        "id": f"doc-{index}", "filename": title, "nickname": None,
        "channel_linked_at": None, "last_uploaded_at": None, "is_canonical": True,
        "created_at": BASE + timedelta(minutes=index),
    } for index, title in enumerate(TITLES)]
    for key, fields in extra.items():
        rows[int(key.removeprefix("d"))].update(fields)
    return rows


def test_generic_questions_are_not_scoped() -> None:
    for question in (
        "Which acquisition pathway applies to commercial cloud hosting?",
        "How should we manage risk on a software program?",
        "What does the guidebook say about agile?",
        "What are the vendor lock-in risks for cloud?",
        "What are the risks of cloud computing acquisition?",
    ):
        assert resolve_scope(question, library()) is None, question


def test_filename_match_needs_most_of_the_title() -> None:
    scope = resolve_scope("Summarize the DoD Cloud Computing Acquisition Guidebook for me", library())
    assert scope and scope.reason == "filename" and scope.document_ids == [f"doc-{CLOUD}"]
    scope = resolve_scope("what does the agile software acquisition guidebook require for testing?", library())
    assert scope and scope.document_ids == [f"doc-{AGILE_SOFTWARE}"]


def test_nickname_beats_everything_and_is_case_insensitive() -> None:
    docs = library(d24={"nickname": "Cloud Book"})
    scope = resolve_scope("In the CLOUD book, what is vendor lock-in?", docs)
    assert scope and scope.reason == "nickname" and scope.document_ids == ["doc-24"]
    assert scope.label == "Cloud Book"


def test_longest_nickname_wins() -> None:
    docs = library(d3={"nickname": "aaf"}, d6={"nickname": "aaf card v37"})
    scope = resolve_scope("what is on the aaf card v37?", docs)
    assert scope.document_ids == ["doc-6"]


def test_just_uploaded_prefers_this_channel_then_newest_anywhere() -> None:
    day = lambda n: BASE + timedelta(days=n)  # noqa: E731
    docs = library(
        d1={"channel_linked_at": day(1), "last_uploaded_at": day(1)},
        d2={"channel_linked_at": day(2), "last_uploaded_at": day(2)},
        # uploaded more recently, but in a different channel
        d5={"last_uploaded_at": day(9)},
    )
    assert resolve_scope("summarize the document I just uploaded", docs).document_ids == ["doc-2"]
    assert resolve_scope("what is in this pdf?", docs).document_ids == ["doc-2"]


def test_just_uploaded_in_a_channel_with_no_uploads_uses_newest_anywhere() -> None:
    day = lambda n: BASE + timedelta(days=n)  # noqa: E731
    docs = library(d1={"last_uploaded_at": day(1)}, d5={"last_uploaded_at": day(3)})
    assert resolve_scope("summarize the document I just uploaded", docs).document_ids == ["doc-5"]


def test_imported_library_never_counts_as_just_uploaded() -> None:
    # nothing was ever uploaded, only imported: search the whole library
    assert resolve_scope("what is in this pdf?", library()) is None


def test_just_uploaded_without_any_upload_is_unscoped() -> None:
    assert resolve_scope("summarize the document I just uploaded", library()) is None


def test_superseded_versions_only_searchable_when_historical_requested() -> None:
    docs = library(d3={"is_canonical": False, "nickname": "old card"})
    assert resolve_scope("what is in the old card?", docs) is None
    scope = resolve_scope("what is in the old card?", docs, include_historical=True)
    assert scope and scope.document_ids == ["doc-3"]


def test_single_token_upload_is_matched_by_name() -> None:
    docs = [{"id": "x", "filename": "Zebra.pdf", "nickname": None, "channel_linked_at": BASE,
             "last_uploaded_at": BASE, "is_canonical": True, "created_at": BASE}]
    assert resolve_scope("what does the zebra pdf say about stripes?", docs).document_ids == ["x"]
    # no document word -> treated as a topical question, not a document reference
    assert resolve_scope("what does zebra say about stripes?", docs) is None


def test_wants_historical() -> None:
    assert wants_historical("what changed in the previous version?")
    assert wants_historical("rules in 2019")
    assert not wants_historical("what is the pathway?")


@pytest.mark.parametrize(("stage", "done", "total", "expected"), [
    ("queued", 0, 0, 0), ("parsing", 0, 0, 5), ("embedding", 0, 100, 20),
    ("embedding", 50, 100, 58), ("embedding", 100, 100, 95), ("embedding", 500, 100, 95),
    ("storing", 0, 0, 95), ("ready", 0, 0, 100), ("bogus", 1, 2, 0), (None, None, None, 0),
])
def test_progress_percent(stage, done, total, expected) -> None:
    assert progress_percent(stage, done, total) == expected


def test_progress_label() -> None:
    assert progress_label("embedding", 64, 300) == "embedding 64/300 chunks"
    assert progress_label("ocr", 0, 0) == "running OCR"
