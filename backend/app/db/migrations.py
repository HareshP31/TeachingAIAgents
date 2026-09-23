from __future__ import annotations

from app.db.database import Database


MIGRATION_SQL = """
CREATE EXTENSION IF NOT EXISTS vector;
CREATE TABLE IF NOT EXISTS corpus_imports (
 id uuid PRIMARY KEY, archive_filename text NOT NULL, archive_sha256 text NOT NULL UNIQUE,
 status text NOT NULL CHECK (status IN ('pending','processing','ready','partial','failed')),
 manifest jsonb NOT NULL DEFAULT '[]'::jsonb, summary jsonb NOT NULL DEFAULT '{}'::jsonb,
 error text, created_at timestamptz NOT NULL DEFAULT now(), updated_at timestamptz NOT NULL DEFAULT now(),
 completed_at timestamptz
);
CREATE TABLE IF NOT EXISTS documents (
 id uuid PRIMARY KEY, slack_file_id text UNIQUE, filename text NOT NULL,
 sha256 text NOT NULL UNIQUE, mime_type text NOT NULL DEFAULT 'application/pdf',
 storage_path text NOT NULL, status text NOT NULL CHECK (status IN ('pending','processing','ready','failed','duplicate')),
 chunk_count integer NOT NULL DEFAULT 0, error text,
 created_at timestamptz NOT NULL DEFAULT now(), updated_at timestamptz NOT NULL DEFAULT now()
);
ALTER TABLE documents ADD COLUMN IF NOT EXISTS corpus_import_id uuid REFERENCES corpus_imports(id);
ALTER TABLE documents ADD COLUMN IF NOT EXISTS source_member text;
ALTER TABLE documents ADD COLUMN IF NOT EXISTS page_count integer;
ALTER TABLE documents ADD COLUMN IF NOT EXISTS text_char_count bigint;
ALTER TABLE documents ADD COLUMN IF NOT EXISTS extraction_method text;
ALTER TABLE documents ADD COLUMN IF NOT EXISTS version_family text;
ALTER TABLE documents ADD COLUMN IF NOT EXISTS is_canonical boolean NOT NULL DEFAULT true;
ALTER TABLE documents ADD COLUMN IF NOT EXISTS superseded_by uuid REFERENCES documents(id);
CREATE INDEX IF NOT EXISTS documents_corpus_import_idx ON documents(corpus_import_id);
CREATE INDEX IF NOT EXISTS documents_canonical_idx ON documents(is_canonical) WHERE status='ready';
CREATE TABLE IF NOT EXISTS chunks (
 id bigserial PRIMARY KEY, document_id uuid NOT NULL REFERENCES documents(id) ON DELETE CASCADE,
 ordinal integer NOT NULL, page_start integer NOT NULL, page_end integer NOT NULL,
 text text NOT NULL, embedding vector(1024) NOT NULL, metadata jsonb NOT NULL DEFAULT '{}'::jsonb,
 UNIQUE(document_id, ordinal)
);
CREATE INDEX IF NOT EXISTS chunks_embedding_hnsw ON chunks USING hnsw (embedding vector_cosine_ops);
CREATE TABLE IF NOT EXISTS conversation_runs (
 id uuid PRIMARY KEY, source_event_id text UNIQUE, thread_id text NOT NULL, channel_id text NOT NULL,
 requester_id text NOT NULL, question text NOT NULL, route text, route_reason text,
 status text NOT NULL CHECK (status IN ('queued','running','awaiting_review','completed','failed')),
 used_researcher boolean NOT NULL DEFAULT false, research_findings jsonb NOT NULL DEFAULT '[]'::jsonb,
 draft text, final_answer text, risk_score integer NOT NULL DEFAULT 0,
 risk_breakdown jsonb NOT NULL DEFAULT '{}'::jsonb, risk_flags jsonb NOT NULL DEFAULT '[]'::jsonb,
 citation_issues jsonb NOT NULL DEFAULT '[]'::jsonb, review_status text,
 revision_count integer NOT NULL DEFAULT 0, error_code text, error_message text,
 created_at timestamptz NOT NULL DEFAULT now(), updated_at timestamptz NOT NULL DEFAULT now(), completed_at timestamptz
);
CREATE INDEX IF NOT EXISTS conversation_runs_created_idx ON conversation_runs(created_at DESC);
CREATE TABLE IF NOT EXISTS run_log (
 id bigserial PRIMARY KEY, run_id uuid NOT NULL REFERENCES conversation_runs(id) ON DELETE CASCADE,
 sequence integer NOT NULL, node text NOT NULL, status text NOT NULL, summary text NOT NULL,
 details jsonb NOT NULL DEFAULT '{}'::jsonb, created_at timestamptz NOT NULL DEFAULT now(), UNIQUE(run_id, sequence)
);
CREATE TABLE IF NOT EXISTS app_settings (
 singleton boolean PRIMARY KEY DEFAULT true CHECK (singleton), always_review boolean NOT NULL DEFAULT false,
 updated_at timestamptz NOT NULL DEFAULT now()
);
INSERT INTO app_settings(singleton, always_review) VALUES (true, false) ON CONFLICT (singleton) DO NOTHING;
"""


async def migrate(database: Database) -> None:
    async with database.connection() as conn:
        await conn.execute(MIGRATION_SQL)
        await conn.commit()
