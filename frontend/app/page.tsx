"use client";

import {useEffect, useMemo, useState} from "react";
import {Activity, BookOpen, Bot, CircleAlert, Database, FileText, ShieldCheck} from "lucide-react";
import {GraphTrace} from "@/components/graph-trace";
import {RiskCard} from "@/components/risk-card";
import type {Overview, Ready, RunDetail} from "@/lib/types";

const API = process.env.NEXT_PUBLIC_API_URL ?? "http://localhost:8000";
const activeStates = new Set(["queued", "running", "awaiting_review"]);

function age(value: string) {
  const seconds = Math.max(0, Math.round((Date.now() - new Date(value).getTime()) / 1000));
  if (seconds < 60) return `${seconds}s ago`;
  if (seconds < 3600) return `${Math.floor(seconds / 60)}m ago`;
  return `${Math.floor(seconds / 3600)}h ago`;
}

export default function Dashboard() {
  const [overview, setOverview] = useState<Overview>();
  const [ready, setReady] = useState<Ready>();
  const [selectedId, setSelectedId] = useState<string>();
  const [run, setRun] = useState<RunDetail>();
  const [error, setError] = useState<string>();

  useEffect(() => {
    let stopped = false;
    let timer: ReturnType<typeof setTimeout>;
    async function poll() {
      try {
        const [overviewResponse, readyResponse] = await Promise.all([
          fetch(`${API}/api/overview`, {cache: "no-store"}),
          fetch(`${API}/health/ready`, {cache: "no-store"}),
        ]);
        if (!overviewResponse.ok || !readyResponse.ok) throw new Error("Backend unavailable");
        const nextOverview: Overview = await overviewResponse.json();
        const nextReady: Ready = await readyResponse.json();
        if (stopped) return;
        setOverview(nextOverview); setReady(nextReady); setError(undefined);
        const target = selectedId ?? nextOverview.runs[0]?.id;
        if (target) {
          if (!selectedId) setSelectedId(target);
          const detailResponse = await fetch(`${API}/api/runs/${target}`, {cache: "no-store"});
          if (detailResponse.ok) setRun(await detailResponse.json());
        }
        const active = nextOverview.runs.some(item => activeStates.has(item.status));
        timer = setTimeout(poll, active ? 1500 : 10000);
      } catch (reason) {
        if (!stopped) {setError(reason instanceof Error ? reason.message : "Connection failed"); timer = setTimeout(poll, 5000);}
      }
    }
    poll();
    return () => {stopped = true; clearTimeout(timer);};
  }, [selectedId]);

  const nodeLog = run?.log ?? [];
  const dependencyCount = useMemo(() => Object.values(ready?.checks ?? {}).filter(Boolean).length, [ready]);
  const latestImport = overview?.imports?.[0];

  return <main>
    <header>
      <div className="brand"><div className="brand-mark"><ShieldCheck/></div><div><h1>Teaching AI Agents</h1><p>Acquisition research · local operations console</p></div></div>
      <div className="header-status"><span className={`pulse ${ready?.status === "ready" ? "online" : "offline"}`}/>
        <div><b>{ready?.status === "ready" ? "SYSTEM READY" : "SYSTEM DEGRADED"}</b><small>{dependencyCount}/4 services · {overview?.mode ?? "connecting"} mode</small></div>
      </div>
    </header>

    {error && <div className="error-banner"><CircleAlert size={16}/>{error}; retrying automatically.</div>}

    <div className="dashboard-grid">
      <aside className="left-stack">
        <section className="panel runs-panel"><div className="panel-heading"><span>Recent runs</span><Activity size={16}/></div>
          <div className="run-list">{overview?.runs.length ? overview.runs.map(item =>
            <button key={item.id} className={selectedId === item.id ? "selected" : ""} onClick={() => setSelectedId(item.id)}>
              <span className={`status-rail ${item.status}`}/><span className="run-copy"><b>{item.question}</b><small>{item.route ?? "routing"} · {age(item.created_at)}</small></span><strong>{item.risk_score}</strong>
            </button>) : <div className="empty"><Bot/><span>No agent runs yet</span></div>}</div>
        </section>
        <section className="panel documents-panel"><div className="panel-heading"><span>Document repository</span><span className="eyebrow">{latestImport ? `${latestImport.status} · ${latestImport.summary?.ready ?? 0}/${latestImport.summary?.total ?? 0}` : "NO IMPORT"}</span></div>
          <div className="document-list">{overview?.documents.length ? overview.documents.map(document =>
            <div key={document.id}><div className="file-icon"><FileText size={15}/></div><span><b>{document.filename}</b><small>{document.page_count ?? "?"} pages · {document.chunk_count} vectors · {document.extraction_method ?? document.status}{document.is_canonical ? " · canonical" : " · historical"}</small></span><i className={document.status}/></div>) :
            <div className="empty"><BookOpen/><span>Upload a PDF in Slack</span></div>}</div>
        </section>
      </aside>

      <section className="center-stack">
        <section className="panel trace-panel"><div className="panel-heading"><span>LangGraph execution trace</span><span className="eyebrow">LIVE</span></div>
          <div className="question"><small>ACTIVE QUERY</small><h2>{run?.question ?? "Waiting for a Slack request"}</h2></div>
          <GraphTrace log={nodeLog}/>
          <div className="answer"><small>LATEST DRAFT / FINAL</small><p>{run?.final_answer ?? run?.draft ?? "Agent output will appear here as the graph advances."}</p></div>
        </section>
        <section className="panel audit-panel"><div className="panel-heading"><span>Audit stream</span><span>{nodeLog.length} events</span></div>
          <div className="audit-list">{nodeLog.length ? nodeLog.slice().reverse().map(item =>
            <div key={`${item.sequence}-${item.node}`}><time>{new Date(item.created_at).toLocaleTimeString([], {hour: "2-digit", minute: "2-digit", second: "2-digit"})}</time><span className="audit-node">{item.node}</span><p>{item.summary}</p></div>) : <div className="empty"><Activity/><span>No telemetry yet</span></div>}</div>
        </section>
      </section>

      <aside className="right-stack">
        <RiskCard run={run}/>
        <section className="panel sources-panel"><div className="panel-heading"><span>Evidence</span><span>{(run?.research_findings?.length ?? 0) + (run?.citation_issues?.length ?? 0)}</span></div>
          <div className="source-list">{run?.research_findings?.map((source, index) =>
            <a href={source.url} target="_blank" rel="noreferrer" key={source.url}><span>{index + 1}</span><div><b>{source.title}</b><small>{new URL(source.url).hostname}</small></div></a>)}
            {run?.citation_issues?.map(issue => <div className="issue" key={`${issue.citation}-${issue.reason}`}><CircleAlert/><span><b>{issue.citation}</b><small>{issue.reason}</small></span></div>)}
            {!run?.research_findings?.length && !run?.citation_issues?.length && <div className="empty"><FileText/><span>No external evidence</span></div>}
          </div>
        </section>
      </aside>
    </div>
    <footer><span>LOCAL-FIRST · POSTGRES + PGVECTOR · QWEN VIA LM STUDIO</span><span>Polling securely from {API}</span></footer>
  </main>;
}
