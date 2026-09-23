from __future__ import annotations

from typing import Any
from uuid import UUID, uuid4

from psycopg.rows import dict_row
from psycopg.types.json import Jsonb

from app.db.database import Database


def _vector(values: list[float]) -> str:
    return "[" + ",".join(f"{value:.8f}" for value in values) + "]"


class Repository:
    def __init__(self, database: Database) -> None:
        self.database = database

    async def create_corpus_import(
        self, *, archive_filename: str, archive_sha256: str,
    ) -> tuple[UUID, bool]:
        import_id = uuid4()
        async with self.database.connection() as conn, conn.transaction():
            cursor = await conn.execute(
                """INSERT INTO corpus_imports(id, archive_filename, archive_sha256, status)
                   VALUES (%s,%s,%s,'pending') ON CONFLICT (archive_sha256) DO NOTHING
                   RETURNING id""",
                (import_id, archive_filename, archive_sha256),
            )
            row = await cursor.fetchone()
            if row:
                return row[0], True
            cursor = await conn.execute(
                "SELECT id FROM corpus_imports WHERE archive_sha256=%s", (archive_sha256,),
            )
            existing = await cursor.fetchone()
            return existing[0], False

    async def update_corpus_import(
        self, import_id: str | UUID, *, status: str,
        manifest: list[dict[str, Any]] | None = None,
        summary: dict[str, Any] | None = None, error: str | None = None,
    ) -> None:
        completed = status in {"ready", "partial", "failed"}
        async with self.database.connection() as conn, conn.transaction():
            await conn.execute(
                """UPDATE corpus_imports SET status=%s,
                   manifest=COALESCE(%s, manifest), summary=COALESCE(%s, summary),
                   error=%s, updated_at=now(),
                   completed_at=CASE WHEN %s THEN now() ELSE completed_at END
                   WHERE id=%s""",
                (status, Jsonb(manifest) if manifest is not None else None,
                 Jsonb(summary) if summary is not None else None, error, completed, import_id),
            )

    async def get_corpus_import(self, import_id: str | UUID) -> dict[str, Any] | None:
        async with self.database.connection() as conn:
            async with conn.cursor(row_factory=dict_row) as cursor:
                await cursor.execute("SELECT * FROM corpus_imports WHERE id=%s", (import_id,))
                return await cursor.fetchone()

    async def list_corpus_imports(self, limit: int = 25) -> list[dict[str, Any]]:
        async with self.database.connection() as conn:
            async with conn.cursor(row_factory=dict_row) as cursor:
                await cursor.execute(
                    """SELECT id, archive_filename, archive_sha256, status, summary, error,
                              created_at, updated_at, completed_at
                       FROM corpus_imports ORDER BY created_at DESC LIMIT %s""", (limit,),
                )
                return list(await cursor.fetchall())

    async def corpus_document_summary(self, import_id: str | UUID) -> dict[str, int]:
        async with self.database.connection() as conn:
            async with conn.cursor(row_factory=dict_row) as cursor:
                await cursor.execute(
                    """SELECT count(*) FILTER (WHERE status='ready')::int AS ready,
                              count(*) FILTER (WHERE status='failed')::int AS failed,
                              count(*) FILTER (WHERE extraction_method='ocr')::int AS ocr,
                              COALESCE(sum(page_count) FILTER (WHERE status='ready'),0)::int AS pages,
                              COALESCE(sum(chunk_count) FILTER (WHERE status='ready'),0)::int AS chunks
                       FROM documents WHERE corpus_import_id=%s""", (import_id,),
                )
                return dict(await cursor.fetchone())

    async def cleanup(self, kind: str) -> dict[str, int]:
        counts = {"documents": 0, "runs": 0}
        async with self.database.connection() as conn, conn.transaction():
            if kind == "synthetic":
                cursor = await conn.execute(
                    "DELETE FROM documents WHERE filename IN ('fixture.pdf','live-fixture.pdf')",
                )
                counts["documents"] = cursor.rowcount
                cursor = await conn.execute(
                    "DELETE FROM conversation_runs WHERE channel_id='dev' AND requester_id='developer'",
                )
                counts["runs"] = cursor.rowcount
            elif kind == "failed":
                cursor = await conn.execute("DELETE FROM documents WHERE status='failed'")
                counts["documents"] = cursor.rowcount
                cursor = await conn.execute("DELETE FROM conversation_runs WHERE status='failed'")
                counts["runs"] = cursor.rowcount
            elif kind == "stale":
                cursor = await conn.execute(
                    """UPDATE conversation_runs SET status='failed', error_code='stale_run',
                              error_message='Marked stale by operator cleanup', completed_at=now(),
                              updated_at=now()
                       WHERE status IN ('queued','running')
                         AND updated_at < now() - interval '24 hours'""",
                )
                counts["runs"] = cursor.rowcount
            else:
                raise ValueError(f"Unknown cleanup kind: {kind}")
        return counts

    async def create_run(
        self, *, source_event_id: str | None, thread_id: str, channel_id: str,
        requester_id: str, question: str,
    ) -> UUID | None:
        run_id = uuid4()
        query = """
            INSERT INTO conversation_runs
              (id, source_event_id, thread_id, channel_id, requester_id, question, status)
            VALUES (%s,%s,%s,%s,%s,%s,'queued')
            ON CONFLICT (source_event_id) DO NOTHING RETURNING id
        """
        async with self.database.connection() as conn, conn.transaction():
            cursor = await conn.execute(
                query, (run_id, source_event_id, thread_id, channel_id, requester_id, question)
            )
            row = await cursor.fetchone()
            return row[0] if row else None

    async def update_run(self, run_id: str | UUID, **fields: Any) -> None:
        allowed = {
            "route", "route_reason", "status", "used_researcher", "research_findings",
            "draft", "final_answer", "risk_score", "risk_breakdown", "risk_flags",
            "citation_issues", "review_status", "revision_count", "error_code", "error_message",
        }
        clean = {key: value for key, value in fields.items() if key in allowed}
        if not clean:
            return
        json_fields = {"research_findings", "risk_breakdown", "risk_flags", "citation_issues"}
        values = [Jsonb(value) if key in json_fields else value for key, value in clean.items()]
        assignments = [f"{key} = %s" for key in clean]
        assignments.append("updated_at = now()")
        if clean.get("status") in {"completed", "failed"}:
            assignments.append("completed_at = now()")
        async with self.database.connection() as conn, conn.transaction():
            await conn.execute(
                f"UPDATE conversation_runs SET {', '.join(assignments)} WHERE id = %s",
                (*values, run_id),
            )

    async def log_node(
        self, run_id: str | UUID, node: str, summary: str,
        *, status: str = "completed", details: dict[str, Any] | None = None,
    ) -> None:
        query = """
          INSERT INTO run_log(run_id, sequence, node, status, summary, details)
          SELECT %s, COALESCE(MAX(sequence), 0) + 1, %s, %s, %s, %s
          FROM run_log WHERE run_id = %s
        """
        async with self.database.connection() as conn, conn.transaction():
            await conn.execute(query, (run_id, node, status, summary, Jsonb(details or {}), run_id))

    async def log_node_once(
        self, run_id: str | UUID, node: str, status: str, summary: str,
    ) -> None:
        query = """
          INSERT INTO run_log(run_id, sequence, node, status, summary, details)
          SELECT %s, COALESCE(MAX(sequence), 0) + 1, %s, %s, %s, '{}'::jsonb
          FROM run_log WHERE run_id = %s
          HAVING NOT EXISTS (
            SELECT 1 FROM run_log WHERE run_id=%s AND node=%s AND status=%s
          )
        """
        async with self.database.connection() as conn, conn.transaction():
            await conn.execute(
                query, (run_id, node, status, summary, run_id, run_id, node, status),
            )

    async def always_review(self) -> bool:
        async with self.database.connection() as conn:
            cursor = await conn.execute("SELECT always_review FROM app_settings WHERE singleton")
            row = await cursor.fetchone()
            return bool(row and row[0])

    async def set_always_review(self, enabled: bool) -> None:
        async with self.database.connection() as conn, conn.transaction():
            await conn.execute(
                "UPDATE app_settings SET always_review=%s, updated_at=now() WHERE singleton", (enabled,)
            )

    async def create_document(
        self, *, filename: str, sha256: str, storage_path: str,
        slack_file_id: str | None = None, corpus_import_id: str | UUID | None = None,
        source_member: str | None = None,
    ) -> tuple[UUID, bool]:
        document_id = uuid4()
        query = """
          INSERT INTO documents
            (id, slack_file_id, filename, sha256, storage_path, status,
             corpus_import_id, source_member)
          VALUES (%s,%s,%s,%s,%s,'pending',%s,%s)
          ON CONFLICT (sha256) DO NOTHING RETURNING id
        """
        async with self.database.connection() as conn, conn.transaction():
            cursor = await conn.execute(
                query, (document_id, slack_file_id, filename, sha256, storage_path,
                        corpus_import_id, source_member),
            )
            row = await cursor.fetchone()
            if row:
                return row[0], True
            cursor = await conn.execute(
                "SELECT id,status FROM documents WHERE sha256=%s FOR UPDATE", (sha256,)
            )
            existing = await cursor.fetchone()
            if existing[1] == "failed":
                await conn.execute("DELETE FROM chunks WHERE document_id=%s", (existing[0],))
                await conn.execute(
                    """UPDATE documents SET slack_file_id=COALESCE(%s,slack_file_id),
                              filename=%s, storage_path=%s, status='pending', error=NULL,
                              chunk_count=0, page_count=NULL, text_char_count=NULL,
                              extraction_method=NULL,
                              corpus_import_id=COALESCE(%s,corpus_import_id),
                              source_member=COALESCE(%s,source_member), updated_at=now()
                       WHERE id=%s""",
                    (slack_file_id, filename, storage_path, corpus_import_id,
                     source_member, existing[0]),
                )
                return existing[0], True
            return existing[0], False

    async def update_document(
        self, document_id: str | UUID, *, status: str,
        chunk_count: int = 0, error: str | None = None,
        page_count: int | None = None, text_char_count: int | None = None,
        extraction_method: str | None = None,
    ) -> None:
        async with self.database.connection() as conn, conn.transaction():
            await conn.execute(
                """UPDATE documents SET status=%s, chunk_count=%s, error=%s,
                   page_count=COALESCE(%s,page_count),
                   text_char_count=COALESCE(%s,text_char_count),
                   extraction_method=COALESCE(%s,extraction_method), updated_at=now()
                   WHERE id=%s""",
                (status, chunk_count, error, page_count, text_char_count,
                 extraction_method, document_id),
            )

    async def set_document_version(
        self, document_id: str | UUID, *, version_family: str,
        is_canonical: bool, superseded_by: str | UUID | None,
    ) -> None:
        async with self.database.connection() as conn, conn.transaction():
            await conn.execute(
                """UPDATE documents SET version_family=%s, is_canonical=%s,
                   superseded_by=%s, updated_at=now() WHERE id=%s""",
                (version_family, is_canonical, superseded_by, document_id),
            )

    async def replace_chunks(self, document_id: str | UUID, chunks: list[dict[str, Any]]) -> None:
        async with self.database.connection() as conn, conn.transaction():
            await conn.execute("DELETE FROM chunks WHERE document_id=%s", (document_id,))
            for chunk in chunks:
                await conn.execute(
                    """INSERT INTO chunks
                       (document_id, ordinal, page_start, page_end, text, embedding, metadata)
                       VALUES (%s,%s,%s,%s,%s,%s::vector,%s)""",
                    (document_id, chunk["ordinal"], chunk["page_start"], chunk["page_end"],
                     chunk["text"], _vector(chunk["embedding"]), Jsonb(chunk.get("metadata", {}))),
                )

    async def search_chunks(
        self, embedding: list[float], limit: int = 8, *, include_historical: bool = False,
    ) -> list[dict[str, Any]]:
        query = """
          SELECT c.id, c.document_id, c.text, c.page_start, c.page_end, d.filename,
                 d.version_family,
                 1 - (c.embedding <=> %s::vector) AS score
          FROM chunks c JOIN documents d ON d.id=c.document_id
          WHERE d.status='ready' AND (%s OR d.is_canonical)
          ORDER BY c.embedding <=> %s::vector LIMIT %s
        """
        value = _vector(embedding)
        async with self.database.connection() as conn:
            async with conn.cursor(row_factory=dict_row) as cursor:
                await cursor.execute(query, (value, include_historical, value, limit))
                rows = list(await cursor.fetchall())
                if not include_historical:
                    return rows
                families = sorted({row["version_family"] for row in rows if row["version_family"]})
                if not families:
                    return rows
                await cursor.execute(
                    """WITH ranked AS (
                         SELECT c.id, c.document_id, c.text, c.page_start, c.page_end,
                                d.filename, d.version_family,
                                1 - (c.embedding <=> %s::vector) AS score,
                                row_number() OVER (
                                  PARTITION BY c.document_id ORDER BY c.embedding <=> %s::vector
                                ) AS document_rank
                         FROM chunks c JOIN documents d ON d.id=c.document_id
                         WHERE d.status='ready' AND d.version_family = ANY(%s)
                       )
                       SELECT id,document_id,text,page_start,page_end,filename,version_family,score
                       FROM ranked WHERE document_rank=1 ORDER BY score DESC""",
                    (value, value, families),
                )
                present = {row["document_id"] for row in rows}
                companions = [
                    row for row in await cursor.fetchall() if row["document_id"] not in present
                ]
                if not companions:
                    return rows
                return rows[:max(0, limit - len(companions))] + companions[:limit]

    async def list_documents(self, limit: int = 100) -> list[dict[str, Any]]:
        async with self.database.connection() as conn:
            async with conn.cursor(row_factory=dict_row) as cursor:
                await cursor.execute(
                    """SELECT id, filename, status, chunk_count, error, page_count,
                              text_char_count, extraction_method, version_family,
                              is_canonical, superseded_by, corpus_import_id,
                              created_at, updated_at
                       FROM documents ORDER BY created_at DESC LIMIT %s""", (limit,)
                )
                return list(await cursor.fetchall())

    async def list_runs(self, limit: int = 25, status: str | None = None) -> list[dict[str, Any]]:
        params: list[Any] = []
        where = ""
        if status:
            where = "WHERE status=%s"
            params.append(status)
        params.append(limit)
        async with self.database.connection() as conn:
            async with conn.cursor(row_factory=dict_row) as cursor:
                await cursor.execute(
                    f"""SELECT id, question, route, status, risk_score, risk_flags, review_status,
                                revision_count, created_at, updated_at
                         FROM conversation_runs {where} ORDER BY created_at DESC LIMIT %s""", params,
                )
                return list(await cursor.fetchall())

    async def get_run(self, run_id: str | UUID) -> dict[str, Any] | None:
        async with self.database.connection() as conn:
            async with conn.cursor(row_factory=dict_row) as cursor:
                await cursor.execute("SELECT * FROM conversation_runs WHERE id=%s", (run_id,))
                run = await cursor.fetchone()
                if not run:
                    return None
                await cursor.execute(
                    """SELECT sequence,node,status,summary,details,created_at FROM run_log
                       WHERE run_id=%s ORDER BY sequence""", (run_id,)
                )
                run["log"] = list(await cursor.fetchall())
                return run
