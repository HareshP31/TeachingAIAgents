import type {DocumentPage, DocumentRow, LogRow, Overview, Ready, RunDetail, RunRow} from "@/lib/types";

export const NOW = new Date("2026-10-08T12:00:00Z");

export function makeDoc(overrides: Partial<DocumentRow> = {}): DocumentRow {
  return {
    id: "doc-1", filename: "Cloud Guidebook.pdf", status: "ready", chunk_count: 42,
    page_count: 12, extraction_method: "native", is_canonical: true, nickname: null,
    stage: null, channel_ids: [], progress_percent: 100, progress_label: "ready",
    uploaded_via_slack: false, created_at: "2026-10-07T12:00:00Z", updated_at: "2026-10-07T12:00:00Z",
    ...overrides,
  };
}

export function makeDocPage(items: DocumentRow[], overrides: Partial<DocumentPage> = {}): DocumentPage {
  return {items, total: items.length, limit: 10, offset: 0, ...overrides};
}

export function makeRun(overrides: Partial<RunRow> = {}): RunRow {
  return {
    id: "run-1", question: "What is a product support manager?", route: "analyst", status: "completed",
    risk_score: 0, risk_flags: [], revision_count: 0, created_at: "2026-10-08T11:59:30Z",
    ...overrides,
  };
}

export function makeLog(node: string, overrides: Partial<LogRow> = {}): LogRow {
  return {
    sequence: 1, node, status: "completed", summary: `${node} finished`, details: {},
    created_at: "2026-10-08T11:59:40Z", ...overrides,
  };
}

export function makeRunDetail(overrides: Partial<RunDetail> = {}): RunDetail {
  return {
    ...makeRun(), risk_breakdown: {}, citation_issues: [], research_findings: [], log: [],
    ...overrides,
  };
}

export function makeOverview(overrides: Partial<Overview> = {}): Overview {
  return {
    mode: "live", always_review: false, imports: [], documents: [], ingesting: [],
    document_total: 0, runs: [], ...overrides,
  };
}

export const READY: Ready = {
  status: "ready", mode: "live",
  checks: {postgres: true, nanobot: true, lm_studio: true, slack: true},
};

export const DEGRADED: Ready = {
  status: "degraded", mode: "live",
  checks: {postgres: true, nanobot: false, lm_studio: true, slack: false},
};
