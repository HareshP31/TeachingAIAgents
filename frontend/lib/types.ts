export type DocumentRow = {
  id: string; filename: string; status: string; chunk_count: number; error?: string;
  page_count?: number; text_char_count?: number; extraction_method?: string;
  version_family?: string; is_canonical: boolean; superseded_by?: string;
  corpus_import_id?: string;
  created_at: string; updated_at: string;
};

export type CorpusImportRow = {
  id: string; archive_filename: string; archive_sha256: string; status: string;
  summary?: {total?: number; ready?: number; failed?: number; duplicates?: number};
  error?: string; created_at: string; updated_at: string; completed_at?: string;
};

export type RunRow = {
  id: string; question: string; route?: string; status: string; risk_score: number;
  risk_flags: string[]; review_status?: string; revision_count: number; created_at: string;
};

export type LogRow = {
  sequence: number; node: string; status: string; summary: string;
  details: Record<string, unknown>; created_at: string;
};

export type RunDetail = RunRow & {
  final_answer?: string; draft?: string; risk_breakdown: Record<string, number | boolean>;
  citation_issues: {citation: string; reason: string}[];
  research_findings: {title: string; url: string; excerpt: string}[];
  log: LogRow[];
};

export type Overview = {
  mode: string; always_review: boolean; imports: CorpusImportRow[];
  documents: DocumentRow[]; runs: RunRow[];
};
export type Ready = {status: string; mode: string; checks: Record<string, boolean>};
