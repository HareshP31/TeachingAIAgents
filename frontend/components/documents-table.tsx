"use client";

import {useCallback, useEffect, useState} from "react";
import {ChevronLeft, ChevronRight, Pencil, Search} from "lucide-react";
import type {DocumentPage, DocumentRow} from "@/lib/types";

const PAGE_SIZE = 10;

function added(value: string) {
  return new Date(value).toLocaleString([], {month: "short", day: "numeric", hour: "2-digit", minute: "2-digit"});
}

function Nickname({api, doc, onSaved}: {api: string; doc: DocumentRow; onSaved: () => void}) {
  const [editing, setEditing] = useState(false);
  const [value, setValue] = useState(doc.nickname ?? "");
  const [error, setError] = useState<string>();

  async function save() {
    const response = await fetch(`${api}/api/documents/${doc.id}/nickname`, {
      method: "POST", headers: {"Content-Type": "application/json"},
      body: JSON.stringify({nickname: value.trim() || null}),
    });
    if (response.ok) {setEditing(false); setError(undefined); onSaved(); return;}
    const body = await response.json().catch(() => undefined);
    const detail = body?.detail;
    setError(typeof detail === "string" ? detail : Array.isArray(detail) ? detail[0]?.msg?.replace("Value error, ", "") : "Could not save");
  }

  if (!editing) {
    return <button className="nickname" onClick={() => {setValue(doc.nickname ?? ""); setEditing(true);}} title="Set a short name to use when asking questions">
      {doc.nickname ? <b>{doc.nickname}</b> : <em>add nickname</em>}<Pencil size={11}/>
    </button>;
  }
  return <span className="nickname-edit">
    <input autoFocus value={value} maxLength={40} placeholder="e.g. cloud book" onChange={event => setValue(event.target.value)}
      onKeyDown={event => {if (event.key === "Enter") save(); if (event.key === "Escape") {setEditing(false); setError(undefined);}}}/>
    <button onClick={save}>Save</button>
    {error && <small className="field-error">{error}</small>}
  </span>;
}

export function DocumentsTable({api, refreshKey}: {api: string; refreshKey: string}) {
  const [page, setPage] = useState<DocumentPage>();
  const [offset, setOffset] = useState(0);
  const [search, setSearch] = useState("");
  const [query, setQuery] = useState("");
  const [failed, setFailed] = useState(false);

  useEffect(() => {
    const timer = setTimeout(() => {setQuery(search.trim()); setOffset(0);}, 300);
    return () => clearTimeout(timer);
  }, [search]);

  const load = useCallback(async () => {
    try {
      const params = new URLSearchParams({limit: String(PAGE_SIZE), offset: String(offset)});
      if (query) params.set("q", query);
      const response = await fetch(`${api}/api/documents?${params}`, {cache: "no-store"});
      if (!response.ok) throw new Error("documents unavailable");
      const next: DocumentPage = await response.json();
      if (next.total > 0 && next.items.length === 0 && offset > 0) {setOffset(Math.max(0, offset - PAGE_SIZE)); return;}
      setPage(next); setFailed(false);
    } catch {setFailed(true);}
  }, [api, offset, query]);

  useEffect(() => {load();}, [load, refreshKey]);

  const total = page?.total ?? 0;
  const first = total === 0 ? 0 : offset + 1;
  const last = Math.min(offset + PAGE_SIZE, total);

  return <section className="panel docs-table-panel">
    <div className="panel-heading"><span>Documents · {total}</span>
      <label className="doc-search"><Search size={13}/><input value={search} placeholder="Search name or nickname" onChange={event => setSearch(event.target.value)}/></label>
    </div>
    <div className="docs-scroll"><table>
      <thead><tr><th>Document</th><th>Nickname</th><th>Pages</th><th>Chunks</th><th>Origin</th><th>Added</th><th>Status</th></tr></thead>
      <tbody>{page?.items.map(doc => <tr key={doc.id}>
        <td className="doc-name" title={doc.filename}>{doc.filename}</td>
        <td><Nickname api={api} doc={doc} onSaved={load}/></td>
        <td>{doc.page_count ?? "–"}</td>
        <td>{doc.chunk_count || "–"}</td>
        <td title={doc.channel_ids.length ? `Uploaded in Slack channel(s): ${doc.channel_ids.join(", ")}` : "Imported from the guidebook archive"}>
          {doc.channel_ids.length === 0 ? "Import" : "Slack upload"}</td>
        <td>{added(doc.created_at)}</td>
        <td>{doc.status === "ready"
          ? <span className="pill ready">{doc.is_canonical ? "ready" : "historical"}</span>
          : doc.status === "failed"
            ? <span className="pill failed" title={doc.error}>failed</span>
            : <span className="pill working">{doc.progress_percent}% · {doc.progress_label}</span>}</td>
      </tr>)}
      {page && page.items.length === 0 && <tr><td colSpan={7} className="docs-empty">{query ? "No documents match that search" : "No documents yet. Drop a PDF in Slack."}</td></tr>}
      {!page && <tr><td colSpan={7} className="docs-empty">{failed ? "Documents unavailable; retrying…" : "Loading…"}</td></tr>}
      </tbody></table></div>
    <div className="docs-pager">
      <small>Ask about one with its nickname, e.g. “according to the <b>cloud book</b>…”, or “the document I just uploaded”.</small>
      <span>{first}–{last} of {total}</span>
      <button disabled={offset === 0} onClick={() => setOffset(Math.max(0, offset - PAGE_SIZE))} aria-label="Previous page"><ChevronLeft size={14}/></button>
      <button disabled={offset + PAGE_SIZE >= total} onClick={() => setOffset(offset + PAGE_SIZE)} aria-label="Next page"><ChevronRight size={14}/></button>
    </div>
  </section>;
}
