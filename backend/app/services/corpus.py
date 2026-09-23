from __future__ import annotations

import hashlib
import re
import shutil
import stat
import zipfile
from dataclasses import dataclass
from pathlib import Path, PurePosixPath
from typing import Any
from uuid import UUID

from app.config import Settings
from app.db.repository import Repository
from app.graphs.ingestion_graph import IngestionService


MAX_PDFS = 200
MAX_UNCOMPRESSED_BYTES = 2 * 1024 * 1024 * 1024
MAX_MEMBER_BYTES = 50 * 1024 * 1024
MAX_COMPRESSION_RATIO = 100


class ArchiveValidationError(ValueError):
    pass


@dataclass(frozen=True)
class ArchiveMember:
    name: str
    size: int
    compressed_size: int


def file_sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def validate_archive(path: Path) -> list[ArchiveMember]:
    if path.suffix.lower() != ".zip":
        raise ArchiveValidationError("Only ZIP archives are supported")
    members: list[ArchiveMember] = []
    total = 0
    try:
        archive = zipfile.ZipFile(path)
    except zipfile.BadZipFile as exc:
        raise ArchiveValidationError("Archive is not a valid ZIP file") from exc
    with archive:
        for info in archive.infolist():
            if info.is_dir():
                continue
            pure = PurePosixPath(info.filename.replace("\\", "/"))
            mode = (info.external_attr >> 16) & 0o170000
            if pure.is_absolute() or ".." in pure.parts:
                raise ArchiveValidationError(f"Unsafe archive path: {info.filename}")
            if mode == stat.S_IFLNK:
                raise ArchiveValidationError(f"Symlinks are not allowed: {info.filename}")
            if pure.suffix.lower() != ".pdf":
                raise ArchiveValidationError(f"Non-PDF archive member: {info.filename}")
            if info.file_size > MAX_MEMBER_BYTES:
                raise ArchiveValidationError(f"PDF exceeds 50 MB: {info.filename}")
            ratio = info.file_size / max(info.compress_size, 1)
            if ratio > MAX_COMPRESSION_RATIO:
                raise ArchiveValidationError(f"Suspicious compression ratio: {info.filename}")
            total += info.file_size
            members.append(ArchiveMember(info.filename, info.file_size, info.compress_size))
    if not members:
        raise ArchiveValidationError("Archive contains no PDFs")
    if len(members) > MAX_PDFS:
        raise ArchiveValidationError(f"Archive contains more than {MAX_PDFS} PDFs")
    if total > MAX_UNCOMPRESSED_BYTES:
        raise ArchiveValidationError("Archive exceeds 2 GB uncompressed")
    return sorted(members, key=lambda item: item.name.casefold())


_MONTHS = "jan|feb|mar|apr|may|jun|jul|aug|sep|sept|oct|nov|dec"


def version_family(filename: str) -> str:
    value = Path(filename).stem.lower()
    value = re.sub(r"\b(?:v(?:ersion)?\s*)?\d+(?:\.\d+)+\b", " ", value)
    value = re.sub(rf"\b\d{{1,2}}(?:{_MONTHS})\d{{2,4}}\b", " ", value)
    value = re.sub(rf"\b(?:{_MONTHS})[a-z]*\s*\d{{2,4}}\b", " ", value)
    value = re.sub(r"\b(?:19|20)\d{2}\b", " ", value)
    return re.sub(r"[^a-z0-9]+", " ", value).strip()


def version_sort_key(filename: str) -> tuple[int, tuple[int, ...], str]:
    lower = filename.lower()
    year = 0
    compact = re.search(rf"\b\d{{1,2}}(?:{_MONTHS})(\d{{2,4}})\b", lower)
    named = re.search(rf"\b(?:{_MONTHS})[a-z]*\s*((?:19|20)?\d{{2}})\b", lower)
    plain = re.findall(r"\b((?:19|20)\d{2})\b", lower)
    raw_year = compact.group(1) if compact else named.group(1) if named else plain[-1] if plain else "0"
    if raw_year != "0":
        year = int(raw_year)
        if year < 100:
            year += 2000
    match = re.search(r"\bv(?:ersion)?\s*(\d+(?:\.\d+)*)", lower)
    version = tuple(int(item) for item in match.group(1).split(".")) if match else ()
    return year, version, lower


class CorpusImportService:
    def __init__(
        self, repository: Repository, ingestion: IngestionService, settings: Settings,
    ) -> None:
        self.repository = repository
        self.ingestion = ingestion
        self.settings = settings

    async def import_archive(self, archive_path: Path) -> dict[str, Any]:
        members = validate_archive(archive_path)
        archive_sha = file_sha256(archive_path)
        import_id, created = await self.repository.create_corpus_import(
            archive_filename=archive_path.name, archive_sha256=archive_sha,
        )
        if not created:
            existing = await self.repository.get_corpus_import(import_id)
            if existing and existing["status"] == "ready":
                return {"duplicate": True, "import": existing}

        await self.repository.update_corpus_import(import_id, status="processing")
        staging = self.settings.document_store / "imports" / archive_sha
        staging.mkdir(parents=True, exist_ok=True)
        manifest: list[dict[str, Any]] = []
        try:
            with zipfile.ZipFile(archive_path) as archive:
                for index, member in enumerate(members):
                    safe_name = Path(member.name).name
                    staged = staging / f"{index:03d}-{safe_name}"
                    with archive.open(member.name) as source, staged.open("wb") as target:
                        shutil.copyfileobj(source, target, length=1024 * 1024)
                    row: dict[str, Any] = {
                        "source_member": member.name,
                        "filename": safe_name,
                        "size": member.size,
                        "sha256": file_sha256(staged),
                        "version_family": version_family(safe_name),
                    }
                    try:
                        result = await self.ingestion.ingest_path(
                            staged, corpus_import_id=import_id,
                            source_member=member.name, display_filename=safe_name,
                        )
                        row.update(result)
                        row["status"] = "duplicate" if result.get("duplicate") else "ready"
                    except Exception as exc:
                        row.update(status="failed", error=f"{type(exc).__name__}: {exc}"[:500])
                    manifest.append(row)

            await self._apply_versions(manifest)
            stored = await self.repository.corpus_document_summary(import_id)
            summary = {
                "total": len(manifest),
                "ready": stored["ready"],
                "duplicates": sum(row["status"] == "duplicate" for row in manifest),
                "failed": stored["failed"],
                "ocr": stored["ocr"],
                "pages": stored["pages"],
                "chunks": stored["chunks"],
            }
            status = "partial" if stored["failed"] else "ready"
            await self.repository.update_corpus_import(
                import_id, status=status, manifest=manifest, summary=summary,
            )
            return {
                "duplicate": False, "import_id": str(import_id),
                "status": status, "summary": summary, "manifest": manifest,
            }
        except Exception as exc:
            await self.repository.update_corpus_import(
                import_id, status="failed", manifest=manifest,
                summary={"total": len(members), "processed": len(manifest)},
                error=f"{type(exc).__name__}: {exc}"[:500],
            )
            raise

    async def _apply_versions(self, manifest: list[dict[str, Any]]) -> None:
        families: dict[str, list[dict[str, Any]]] = {}
        for row in manifest:
            if row.get("document_id") and row.get("status") in {"ready", "duplicate"}:
                families.setdefault(row["version_family"], []).append(row)
        for family, rows in families.items():
            canonical = max(rows, key=lambda row: version_sort_key(row["filename"]))
            canonical_id = UUID(canonical["document_id"])
            for row in rows:
                is_canonical = row is canonical
                row["is_canonical"] = is_canonical
                row["superseded_by"] = None if is_canonical else str(canonical_id)
                await self.repository.set_document_version(
                    UUID(row["document_id"]), version_family=family,
                    is_canonical=is_canonical,
                    superseded_by=None if is_canonical else canonical_id,
                )
