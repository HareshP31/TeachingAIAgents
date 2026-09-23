from __future__ import annotations

import sys
from pathlib import Path

from pypdf import PdfWriter
from pypdf._page import PageObject
from pypdf.generic import DictionaryObject, NameObject, NumberObject, StreamObject


def make_pdf(destination: Path) -> None:
    writer = PdfWriter()
    page = PageObject.create_blank_page(width=612, height=792)
    font = DictionaryObject({
        NameObject("/Type"): NameObject("/Font"),
        NameObject("/Subtype"): NameObject("/Type1"),
        NameObject("/BaseFont"): NameObject("/Helvetica"),
    })
    resources = DictionaryObject({
        NameObject("/Font"): DictionaryObject({NameObject("/F1"): writer._add_object(font)}),
    })
    content = StreamObject()
    content.set_data(
        b"BT /F1 12 Tf 72 720 Td (Cloud acquisitions require competition, portability, and exit planning.) Tj ET"
    )
    page[NameObject("/Resources")] = resources
    page[NameObject("/Contents")] = writer._add_object(content)
    page[NameObject("/Rotate")] = NumberObject(0)
    writer.add_page(page)
    destination.parent.mkdir(parents=True, exist_ok=True)
    with destination.open("wb") as handle:
        writer.write(handle)


if __name__ == "__main__":
    make_pdf(Path(sys.argv[1]))
