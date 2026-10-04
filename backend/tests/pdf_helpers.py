from __future__ import annotations

from pathlib import Path

from pypdf import PdfWriter
from pypdf._page import PageObject
from pypdf.generic import DictionaryObject, NameObject, StreamObject


def words(count: int, prefix: str = "w") -> str:
    return " ".join(f"{prefix}{index}" for index in range(count))


def _escape(text: str) -> bytes:
    return text.replace("\\", "\\\\").replace("(", "\\(").replace(")", "\\)").encode("latin-1")


def build_writer(pages: list[str]) -> PdfWriter:
    """One page per entry; an empty string produces a page with no text layer."""
    writer = PdfWriter()
    font = writer._add_object(DictionaryObject({
        NameObject("/Type"): NameObject("/Font"),
        NameObject("/Subtype"): NameObject("/Type1"),
        NameObject("/BaseFont"): NameObject("/Helvetica"),
    }))
    for text in pages:
        page = PageObject.create_blank_page(width=612, height=792)
        if text:
            page[NameObject("/Resources")] = DictionaryObject({
                NameObject("/Font"): DictionaryObject({NameObject("/F1"): font}),
            })
            content = StreamObject()
            content.set_data(b"BT /F1 10 Tf 10 700 Td (" + _escape(text) + b") Tj ET")
            page[NameObject("/Contents")] = writer._add_object(content)
        writer.add_page(page)
    return writer


def make_pdf(
    path: Path, pages: list[str], *, user_password: str | None = None, owner_password: str = "owner",
) -> Path:
    writer = build_writer(pages)
    if user_password is not None:
        writer.encrypt(user_password=user_password, owner_password=owner_password, algorithm="AES-256")
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("wb") as handle:
        writer.write(handle)
    return path
