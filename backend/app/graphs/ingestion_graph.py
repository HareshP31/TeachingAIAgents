from __future__ import annotations

import asyncio
import hashlib
import re
import shutil
from pathlib import Path
from typing import TypedDict
from uuid import UUID

from langgraph.graph import END, START, StateGraph
from pypdf import PdfReader

from app.config import Settings
from app.db.repository import Repository
from app.services.chunking import chunk_pages
from app.services.embeddings import Embedder


class IngestionState(TypedDict, total=False):
    document_id: str
    path: str
    filename: str
    sha256: str
    pages: list[str]
    page_count: int
    text_char_count: int
    extraction_method: str
    chunks: list[dict]
    embeddings: list[list[float]]
    chunk_count: int


class IngestionService:
    def __init__(self, repository: Repository, embedder: Embedder, settings: Settings) -> None:
        self.repository = repository
        self.embedder = embedder
        self.settings = settings
        builder = StateGraph(IngestionState)
        builder.add_node("parse", self._parse)
        builder.add_node("chunk", self._chunk)
        builder.add_node("embed", self._embed)
        builder.add_node("store", self._store)
        builder.add_edge(START, "parse")
        builder.add_edge("parse", "chunk")
        builder.add_edge("chunk", "embed")
        builder.add_edge("embed", "store")
        builder.add_edge("store", END)
        self.graph = builder.compile()

    async def ingest_path(
        self, source: Path, slack_file_id: str | None = None,
        *, corpus_import_id: str | UUID | None = None,
        source_member: str | None = None, display_filename: str | None = None,
    ) -> dict:
        if source.suffix.lower() != ".pdf":
            raise ValueError("Only PDF documents are supported")
        if source.stat().st_size > 50 * 1024 * 1024:
            raise ValueError("PDF exceeds the 50 MB limit")
        digest_builder = hashlib.sha256()
        with source.open("rb") as handle:
            for block in iter(lambda: handle.read(1024 * 1024), b""):
                digest_builder.update(block)
        digest = digest_builder.hexdigest()
        filename = display_filename or source.name
        self.settings.document_store.mkdir(parents=True, exist_ok=True)
        destination = self.settings.document_store / f"{digest}.pdf"
        document_id, created = await self.repository.create_document(
            filename=filename, sha256=digest, storage_path=str(destination),
            slack_file_id=slack_file_id, corpus_import_id=corpus_import_id,
            source_member=source_member,
        )
        if not created:
            return {"document_id": str(document_id), "duplicate": True}
        shutil.copyfile(source, destination)
        await self.repository.update_document(document_id, status="processing")
        try:
            result = await self.graph.ainvoke({
                "document_id": str(document_id), "path": str(destination),
                "filename": filename, "sha256": digest,
            })
            return {
                "document_id": str(document_id), "duplicate": False,
                "chunks": result["chunk_count"], "page_count": result["page_count"],
                "text_char_count": result["text_char_count"],
                "extraction_method": result["extraction_method"],
            }
        except Exception as exc:
            await self.repository.update_document(document_id, status="failed", error=str(exc)[:500])
            raise

    async def _parse(self, state: IngestionState) -> dict:
        path = Path(state["path"])
        pages = await asyncio.to_thread(self._read_pages, path)
        low_pages = sum(len(re.sub(r"\s+", "", page)) < 50 for page in pages)
        average = sum(len(page.strip()) for page in pages) / max(len(pages), 1)
        extraction_method = "native"
        if low_pages / max(len(pages), 1) > 0.30 and average < 100:
            pages = await self._ocr_pages(path)
            extraction_method = "ocr"
        if not any(page.strip() for page in pages):
            raise ValueError("PDF has no extractable text after OCR")
        return {
            "pages": pages, "page_count": len(pages),
            "text_char_count": sum(len(page.strip()) for page in pages),
            "extraction_method": extraction_method,
        }

    @staticmethod
    def _read_pages(path: Path) -> list[str]:
        reader = PdfReader(path)
        if reader.is_encrypted:
            # Many DoD publications carry AES permission flags but use an empty
            # owner/user password. pypdf can open those safely when the crypto
            # extra is installed; genuinely password-protected files still fail.
            if reader.decrypt("") == 0:
                raise ValueError("PDF requires a password")
        if len(reader.pages) > 1000:
            raise ValueError("PDF exceeds the 1000-page limit")
        return [page.extract_text() or "" for page in reader.pages]

    async def _ocr_pages(self, path: Path) -> list[str]:
        output = path.with_suffix(".ocr.pdf")
        try:
            process = await asyncio.create_subprocess_exec(
                "ocrmypdf", "--skip-text", "--rotate-pages", "--deskew",
                "--optimize", "1", "--jobs", "1", str(path), str(output),
                stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE,
            )
            try:
                _, stderr = await asyncio.wait_for(process.communicate(), timeout=600)
            except TimeoutError as exc:
                process.terminate()
                try:
                    await asyncio.wait_for(process.wait(), timeout=5)
                except TimeoutError:
                    process.kill()
                    await process.wait()
                raise ValueError("OCR exceeded the 10-minute limit") from exc
            if process.returncode:
                detail = stderr.decode(errors="ignore")[-300:]
                raise ValueError(f"OCR failed: {detail}")
            return await asyncio.to_thread(self._read_pages, output)
        finally:
            output.unlink(missing_ok=True)

    async def _chunk(self, state: IngestionState) -> dict:
        chunks = chunk_pages(state["pages"])
        return {"chunks": [chunk.__dict__ for chunk in chunks]}

    async def _embed(self, state: IngestionState) -> dict:
        return {"embeddings": await self.embedder.embed([item["text"] for item in state["chunks"]])}

    async def _store(self, state: IngestionState) -> dict:
        payload = []
        for chunk, embedding in zip(state["chunks"], state["embeddings"], strict=True):
            payload.append({
                **chunk, "embedding": embedding,
                "metadata": {
                    "filename": state["filename"], "source_sha256": state["sha256"],
                    "extraction_method": state["extraction_method"],
                },
            })
        await self.repository.replace_chunks(UUID(state["document_id"]), payload)
        await self.repository.update_document(
            UUID(state["document_id"]), status="ready", chunk_count=len(payload),
            page_count=state["page_count"], text_char_count=state["text_char_count"],
            extraction_method=state["extraction_method"],
        )
        return {
            "chunk_count": len(payload), "page_count": state["page_count"],
            "text_char_count": state["text_char_count"],
            "extraction_method": state["extraction_method"],
        }
