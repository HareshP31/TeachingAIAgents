from __future__ import annotations

import asyncio
import hashlib
import shutil
from typing import Any
from uuid import UUID, uuid4

import pytest

from app.config import Settings
from app.graphs import ingestion_graph
from app.graphs.ingestion_graph import IngestionService
from app.services.embeddings import FakeEmbedder
from pdf_helpers import make_pdf, words


class FakeRepository:
    def __init__(self) -> None:
        self.documents: dict[UUID, dict[str, Any]] = {}
        self.by_sha: dict[str, UUID] = {}
        self.create_kwargs: list[dict[str, Any]] = []
        self.uploads: list[tuple[UUID, str]] = []
        self.progress: list[tuple[str, int, int]] = []
        self.chunks: dict[UUID, list[dict[str, Any]]] = {}
        self.fail_progress = False
        self.fail_replace = False

    async def create_document(self, *, filename, sha256, storage_path, slack_file_id,
                              corpus_import_id, source_member):
        self.create_kwargs.append({
            "filename": filename, "slack_file_id": slack_file_id,
            "corpus_import_id": corpus_import_id, "source_member": source_member,
        })
        if sha256 in self.by_sha:
            return self.by_sha[sha256], False
        document_id = uuid4()
        self.by_sha[sha256] = document_id
        self.documents[document_id] = {
            "filename": filename, "sha256": sha256, "storage_path": storage_path, "history": [],
        }
        return document_id, True

    async def record_upload(self, document_id, channel_id) -> None:
        self.uploads.append((document_id, channel_id))

    async def update_document(self, document_id, **fields) -> None:
        document = self.documents[document_id]
        document.update(fields)
        if "status" in fields:
            document["history"].append(fields["status"])

    async def set_document_progress(self, document_id, stage, done, total) -> None:
        if self.fail_progress:
            raise RuntimeError("db down")
        self.progress.append((stage, done, total))

    async def replace_chunks(self, document_id, chunks) -> None:
        if self.fail_replace:
            raise RuntimeError("x" * 900)
        self.chunks[document_id] = chunks


class RecordingEmbedder(FakeEmbedder):
    def __init__(self) -> None:
        super().__init__(dimensions=8)
        self.batches: list[int] = []

    async def embed(self, texts, *, query=False):
        self.batches.append(len(texts))
        return await super().embed(texts, query=query)


@pytest.fixture
def repository() -> FakeRepository:
    return FakeRepository()


@pytest.fixture
def embedder() -> RecordingEmbedder:
    return RecordingEmbedder()


@pytest.fixture
def settings(tmp_path) -> Settings:
    return Settings(app_mode="test", document_store=tmp_path / "store")


@pytest.fixture
def service(repository, embedder, settings) -> IngestionService:
    return IngestionService(repository, embedder, settings)


def healthy_pdf(tmp_path, name: str = "guide.pdf", pages: int = 2):
    return make_pdf(tmp_path / name, [words(60, f"p{index}w") for index in range(pages)])


def only_document(repository: FakeRepository) -> dict[str, Any]:
    assert len(repository.documents) == 1
    return next(iter(repository.documents.values()))


async def test_native_pdf_is_parsed_chunked_embedded_and_stored(tmp_path, service, repository, settings) -> None:
    source = healthy_pdf(tmp_path)
    result = await service.ingest_path(source)

    document = only_document(repository)
    digest = hashlib.sha256(source.read_bytes()).hexdigest()
    assert result["duplicate"] is False
    assert result["filename"] == "guide.pdf"
    assert result["page_count"] == 2
    assert result["extraction_method"] == "native"
    assert result["chunks"] == 1
    assert result["text_char_count"] > 0
    assert document["sha256"] == digest
    assert document["history"] == ["processing", "ready"]
    assert document["status"] == "ready" and document["chunk_count"] == 1
    assert (settings.document_store / f"{digest}.pdf").read_bytes() == source.read_bytes()

    (chunk,) = repository.chunks[next(iter(repository.documents))]
    assert (chunk["page_start"], chunk["page_end"]) == (1, 2)
    assert len(chunk["embedding"]) == 8
    assert chunk["metadata"] == {
        "filename": "guide.pdf", "source_sha256": digest, "extraction_method": "native",
    }


async def test_display_filename_and_corpus_fields_are_forwarded(tmp_path, service, repository) -> None:
    await service.ingest_path(
        healthy_pdf(tmp_path, "raw.pdf"), slack_file_id="F123", corpus_import_id="import-1",
        source_member="folder/raw.pdf", display_filename="Friendly Name.pdf",
    )
    assert repository.create_kwargs == [{
        "filename": "Friendly Name.pdf", "slack_file_id": "F123",
        "corpus_import_id": "import-1", "source_member": "folder/raw.pdf",
    }]


async def test_long_documents_are_embedded_in_batches(tmp_path, service, repository, embedder, monkeypatch) -> None:
    monkeypatch.setattr(ingestion_graph, "EMBED_BATCH", 2)
    source = make_pdf(tmp_path / "long.pdf", [words(1000)])  # 3 chunks at the default size
    result = await service.ingest_path(source)
    assert result["chunks"] == 3
    assert embedder.batches == [2, 1]


async def test_progress_stages_are_reported_in_order(tmp_path, service, repository, monkeypatch) -> None:
    monkeypatch.setattr(ingestion_graph, "EMBED_BATCH", 2)
    seen: list[tuple[str, int, int, int]] = []

    async def on_progress(stage, done, total, percent) -> None:
        seen.append((stage, done, total, percent))

    await service.ingest_path(make_pdf(tmp_path / "long.pdf", [words(1000)]), on_progress=on_progress)

    stages = [stage for stage, *_ in seen]
    assert stages == ["parsing", "chunking", "embedding", "embedding", "embedding", "storing"]
    assert [(done, total) for stage, done, total, _ in seen if stage == "embedding"] == [(0, 3), (2, 3), (3, 3)]
    percents = [percent for *_, percent in seen]
    assert percents == sorted(percents) and 0 <= percents[0] and percents[-1] < 100
    assert [stage for stage, *_ in repository.progress] == stages


async def test_a_failing_progress_callback_does_not_fail_ingestion(tmp_path, service, repository) -> None:
    async def on_progress(*args) -> None:
        raise RuntimeError("slack is down")

    result = await service.ingest_path(healthy_pdf(tmp_path), on_progress=on_progress)
    assert result["duplicate"] is False
    assert only_document(repository)["status"] == "ready"


async def test_a_failing_progress_write_does_not_fail_ingestion(tmp_path, service, repository) -> None:
    repository.fail_progress = True
    await service.ingest_path(healthy_pdf(tmp_path))
    assert only_document(repository)["status"] == "ready"


async def test_duplicate_upload_is_not_reprocessed(tmp_path, service, repository, embedder) -> None:
    first = await service.ingest_path(healthy_pdf(tmp_path, "a.pdf"))
    embedded_once = list(embedder.batches)
    shutil.copy(tmp_path / "a.pdf", tmp_path / "renamed.pdf")
    second = await service.ingest_path(tmp_path / "renamed.pdf")

    assert second == {"document_id": first["document_id"], "duplicate": True, "filename": "renamed.pdf"}
    assert embedder.batches == embedded_once
    assert len(repository.chunks) == 1


async def test_duplicate_upload_in_another_channel_is_still_recorded(tmp_path, service, repository) -> None:
    await service.ingest_path(healthy_pdf(tmp_path), slack_channel_id="C1")
    shutil.copy(tmp_path / "guide.pdf", tmp_path / "again.pdf")
    await service.ingest_path(tmp_path / "again.pdf", slack_channel_id="C2")
    assert [channel for _, channel in repository.uploads] == ["C1", "C2"]


async def test_upload_channel_is_only_recorded_for_slack_uploads(tmp_path, service, repository) -> None:
    await service.ingest_path(healthy_pdf(tmp_path))
    assert repository.uploads == []


@pytest.mark.parametrize("name", ["notes.txt", "scan.PNG", "noextension"])
async def test_non_pdf_files_are_rejected_before_touching_the_database(tmp_path, service, repository, name) -> None:
    source = tmp_path / name
    source.write_bytes(b"hello")
    with pytest.raises(ValueError, match="Only PDF"):
        await service.ingest_path(source)
    assert repository.documents == {} and repository.create_kwargs == []


async def test_uppercase_pdf_extension_is_accepted(tmp_path, service, repository) -> None:
    await service.ingest_path(healthy_pdf(tmp_path, "GUIDE.PDF"))
    assert only_document(repository)["status"] == "ready"


async def test_pdf_over_50_mb_is_rejected_before_touching_the_database(tmp_path, service, repository) -> None:
    source = tmp_path / "huge.pdf"
    with source.open("wb") as handle:
        handle.truncate(50 * 1024 * 1024 + 1)  # sparse file
    with pytest.raises(ValueError, match="50 MB"):
        await service.ingest_path(source)
    assert repository.documents == {}


async def test_pdf_with_empty_password_encryption_is_ingested(tmp_path, service, repository) -> None:
    source = make_pdf(tmp_path / "dod.pdf", [words(60)], user_password="")
    result = await service.ingest_path(source)
    assert result["page_count"] == 1
    assert only_document(repository)["status"] == "ready"


async def test_password_protected_pdf_fails_and_is_marked_failed(tmp_path, service, repository) -> None:
    source = make_pdf(tmp_path / "locked.pdf", [words(60)], user_password="secret")
    with pytest.raises(ValueError, match="password"):
        await service.ingest_path(source)
    document = only_document(repository)
    assert document["status"] == "failed"
    assert "password" in document["error"]
    assert repository.chunks == {}


async def test_pdf_over_1000_pages_fails(tmp_path, service, repository) -> None:
    source = make_pdf(tmp_path / "tome.pdf", [""] * 1001)
    with pytest.raises(ValueError, match="1000-page"):
        await service.ingest_path(source)
    assert only_document(repository)["status"] == "failed"


async def test_corrupt_pdf_fails_and_is_marked_failed(tmp_path, service, repository) -> None:
    source = tmp_path / "broken.pdf"
    source.write_bytes(b"%PDF-1.7 this is not really a pdf")
    with pytest.raises(Exception):
        await service.ingest_path(source)
    assert only_document(repository)["status"] == "failed"


@pytest.fixture
def ocr(monkeypatch):
    class Handle:
        calls = 0
        pages: list[str] = []

    async def fake_ocr(self, path):
        Handle.calls += 1
        return Handle.pages

    monkeypatch.setattr(IngestionService, "_ocr_pages", fake_ocr)
    return Handle


async def test_scanned_pdf_falls_back_to_ocr(tmp_path, service, repository, ocr) -> None:
    ocr.pages = [words(60, "ocr"), words(60, "scan")]
    stages: list[str] = []

    async def on_progress(stage, *rest) -> None:
        stages.append(stage)

    result = await service.ingest_path(make_pdf(tmp_path / "scan.pdf", ["", ""]), on_progress=on_progress)
    assert ocr.calls == 1
    assert result["extraction_method"] == "ocr"
    assert stages[:3] == ["parsing", "ocr", "chunking"]
    (chunk,) = next(iter(repository.chunks.values()))
    assert chunk["metadata"]["extraction_method"] == "ocr"
    assert "ocr0" in chunk["text"]


async def test_ocr_that_finds_no_text_fails_the_document(tmp_path, service, repository, ocr) -> None:
    ocr.pages = ["", "  "]
    with pytest.raises(ValueError, match="no extractable text"):
        await service.ingest_path(make_pdf(tmp_path / "blank.pdf", ["", ""]))
    assert only_document(repository)["status"] == "failed"


async def test_healthy_pdf_never_triggers_ocr(tmp_path, service, ocr) -> None:
    await service.ingest_path(healthy_pdf(tmp_path))
    assert ocr.calls == 0


async def test_a_few_blank_pages_in_a_text_pdf_do_not_trigger_ocr(tmp_path, service, ocr) -> None:
    # 2 of 4 pages are empty (over the 30% page threshold) but the average text is high.
    source = make_pdf(tmp_path / "mixed.pdf", [words(300), "", words(300), ""])
    result = await service.ingest_path(source)
    assert ocr.calls == 0
    assert result["extraction_method"] == "native"


async def test_failure_while_storing_marks_failed_with_truncated_error(tmp_path, service, repository) -> None:
    repository.fail_replace = True
    with pytest.raises(RuntimeError):
        await service.ingest_path(healthy_pdf(tmp_path))
    document = only_document(repository)
    assert document["status"] == "failed"
    assert len(document["error"]) == 500


async def test_a_failed_document_can_be_retried_only_by_new_upload_not_reprocessed(tmp_path, service, repository) -> None:
    """Documents are keyed by content hash, so a retry of the same bytes is reported as a duplicate."""
    repository.fail_replace = True
    with pytest.raises(RuntimeError):
        await service.ingest_path(healthy_pdf(tmp_path))
    repository.fail_replace = False
    retried = await service.ingest_path(tmp_path / "guide.pdf")
    assert retried["duplicate"] is True
    assert only_document(repository)["status"] == "failed"


class FakeProcess:
    def __init__(self, returncode: int = 0, stderr: bytes = b"", hang: bool = False) -> None:
        self.returncode: int | None = None if hang else returncode
        self._stderr, self._hang = stderr, hang
        self.terminated = False

    async def communicate(self):
        if self._hang:
            await asyncio.sleep(3600)
        return b"", self._stderr

    def terminate(self) -> None:
        self.terminated = True
        self.returncode = -15

    def kill(self) -> None:
        self.returncode = -9

    async def wait(self) -> int:
        return self.returncode or 0


def patch_ocr_subprocess(monkeypatch, process: FakeProcess, *, writes_output: bool = False):
    calls: list[tuple] = []

    async def create(*argv, **kwargs):
        calls.append(argv)
        if writes_output:
            shutil.copy(argv[-2], argv[-1])  # pretend ocrmypdf produced a searchable copy
        return process

    monkeypatch.setattr(ingestion_graph.asyncio, "create_subprocess_exec", create)
    return calls


async def test_ocr_subprocess_success_reads_the_output_and_cleans_up(tmp_path, service, monkeypatch) -> None:
    source = healthy_pdf(tmp_path)
    calls = patch_ocr_subprocess(monkeypatch, FakeProcess(), writes_output=True)
    pages = await service._ocr_pages(source)
    argv = calls[0]
    assert argv[0] == "ocrmypdf" and "--skip-text" in argv
    assert argv[argv.index("--jobs") + 1] == "1"
    assert argv[-2] == str(source)
    assert len(pages) == 2 and "p0w0" in pages[0]
    assert not source.with_suffix(".ocr.pdf").exists()


async def test_ocr_subprocess_failure_includes_stderr_tail(tmp_path, service, monkeypatch) -> None:
    patch_ocr_subprocess(monkeypatch, FakeProcess(returncode=3, stderr=b"ghostscript exploded"))
    with pytest.raises(ValueError, match="OCR failed: ghostscript exploded"):
        await service._ocr_pages(healthy_pdf(tmp_path))
    assert not (tmp_path / "guide.ocr.pdf").exists()


async def test_ocr_subprocess_timeout_terminates_the_process(tmp_path, service, monkeypatch) -> None:
    process = FakeProcess(hang=True)
    patch_ocr_subprocess(monkeypatch, process)
    real_wait_for = asyncio.wait_for
    monkeypatch.setattr(ingestion_graph.asyncio, "wait_for", lambda aw, timeout: real_wait_for(aw, 0.01))
    with pytest.raises(ValueError, match="10-minute"):
        await service._ocr_pages(healthy_pdf(tmp_path))
    assert process.terminated is True


async def test_ocr_subprocess_is_killed_if_it_ignores_terminate(tmp_path, service, monkeypatch) -> None:
    class Stubborn(FakeProcess):
        killed = False

        def terminate(self) -> None:
            self.terminated = True  # ignores SIGTERM

        def kill(self) -> None:
            self.killed = True
            self.returncode = -9

        async def wait(self) -> int:
            if not self.killed:
                await asyncio.sleep(3600)
            return self.returncode

    process = Stubborn(hang=True)
    patch_ocr_subprocess(monkeypatch, process)
    real_wait_for = asyncio.wait_for
    monkeypatch.setattr(ingestion_graph.asyncio, "wait_for", lambda aw, timeout: real_wait_for(aw, 0.01))
    with pytest.raises(ValueError, match="10-minute"):
        await service._ocr_pages(healthy_pdf(tmp_path))
    assert process.terminated and process.killed
