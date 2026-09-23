from __future__ import annotations

import zipfile

import pytest

from app.config import Settings
from app.services.corpus import (
    ArchiveValidationError,
    validate_archive,
    version_family,
    version_sort_key,
)


def make_zip(path, members: dict[str, bytes]) -> None:
    with zipfile.ZipFile(path, "w") as archive:
        for name, payload in members.items():
            archive.writestr(name, payload)


def test_valid_archive_and_version_family(tmp_path) -> None:
    path = tmp_path / "guidebooks.zip"
    make_zip(path, {
        "DoD AAF Quick Ref Card --V3.4, 21Oct24.pdf": b"pdf-one",
        "DoD AAF Quick Ref Card --V3.7, 16Sep25.pdf": b"pdf-two",
    })
    members = validate_archive(path)
    assert len(members) == 2
    assert version_family(members[0].name) == version_family(members[1].name)
    assert version_sort_key(members[1].name) > version_sort_key(members[0].name)


@pytest.mark.parametrize("name", ["../escape.pdf", "/absolute.pdf", "notes.txt"])
def test_archive_rejects_unsafe_or_non_pdf_members(tmp_path, name: str) -> None:
    path = tmp_path / "bad.zip"
    make_zip(path, {name: b"payload"})
    with pytest.raises(ArchiveValidationError):
        validate_archive(path)


def test_runtime_rejects_27b_model() -> None:
    settings = Settings(app_mode="local", lm_studio_model="qwen/example-27b")
    assert any("27B" in problem for problem in settings.validate_live())
