import pytest

from app.services.chunking import chunk_pages


def test_chunks_preserve_page_ranges_and_overlap() -> None:
    pages = [" ".join(f"a{i}" for i in range(300)), " ".join(f"b{i}" for i in range(300))]
    chunks = chunk_pages(pages, size=400, overlap=80)
    assert len(chunks) == 2
    assert chunks[0].page_start == 1 and chunks[0].page_end == 2
    assert chunks[1].page_start == 2
    assert chunks[0].text.split()[-80:] == chunks[1].text.split()[:80]


def test_empty_pdf_text_produces_no_chunks() -> None:
    assert chunk_pages(["", "  "]) == []


def test_invalid_window_rejected() -> None:
    with pytest.raises(ValueError):
        chunk_pages(["text"], size=80, overlap=80)
