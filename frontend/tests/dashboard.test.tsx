import {act, fireEvent, render, screen, within} from "@testing-library/react";
import {beforeEach, describe, expect, it, vi} from "vitest";
import Dashboard from "@/app/page";
import type {Overview, Ready, RunDetail} from "@/lib/types";
import {callsTo, json, mockFetch} from "./api";
import {
  DEGRADED, NOW, READY, makeDoc, makeDocPage, makeLog, makeOverview, makeRun, makeRunDetail,
} from "./fixtures";

type World = {
  overview: Overview | (() => Response | Overview);
  ready: Ready | (() => Response | Ready);
  runs: Record<string, RunDetail | Response>;
};

function serve(world: Partial<World> = {}) {
  const state: World = {overview: makeOverview(), ready: READY, runs: {}, ...world};
  const stub = mockFetch(url => {
    const pick = <T,>(value: T | (() => Response | T)) => (typeof value === "function" ? (value as () => Response | T)() : value);
    if (url.pathname === "/api/overview") return pick(state.overview);
    if (url.pathname === "/health/ready") return pick(state.ready);
    if (url.pathname.startsWith("/api/runs/")) return state.runs[url.pathname.split("/").pop()!];
    if (url.pathname === "/api/documents") return makeDocPage([]);
  });
  return {state, stub};
}

/** Render with fake timers and let the first poll settle. */
async function mount() {
  const view = render(<Dashboard/>);
  await settle(0);
  return view;
}

async function settle(ms: number) {
  await act(async () => { await vi.advanceTimersByTimeAsync(ms); });
}

beforeEach(() => {
  vi.useFakeTimers();
  vi.setSystemTime(NOW);
});

describe("Dashboard header", () => {
  it("reports degraded and 'connecting' until the first response arrives", () => {
    serve();
    render(<Dashboard/>);
    expect(screen.getByText("SYSTEM DEGRADED")).toBeInTheDocument();
    expect(screen.getByText("0/4 services · connecting mode")).toBeInTheDocument();
  });

  it("shows ready with all four services up", async () => {
    serve();
    await mount();
    expect(screen.getByText("SYSTEM READY")).toBeInTheDocument();
    expect(screen.getByText("4/4 services · live mode")).toBeInTheDocument();
    expect(document.querySelector(".pulse")).toHaveClass("online");
  });

  it("counts only the healthy services when degraded", async () => {
    serve({ready: DEGRADED});
    await mount();
    expect(screen.getByText("SYSTEM DEGRADED")).toBeInTheDocument();
    expect(screen.getByText("2/4 services · live mode")).toBeInTheDocument();
    expect(document.querySelector(".pulse")).toHaveClass("offline");
  });

  it("polls the configured API with caching disabled", async () => {
    const {stub} = serve();
    await mount();
    const urls = stub.mock.calls.map(([input]) => String(input));
    expect(urls).toContain("http://localhost:8000/api/overview");
    expect(urls).toContain("http://localhost:8000/health/ready");
    for (const [input, init] of stub.mock.calls) {
      if (!String(input).includes("/api/documents")) expect(init).toMatchObject({cache: "no-store"});
    }
    expect(screen.getByText("Polling securely from http://localhost:8000")).toBeInTheDocument();
  });
});

describe("Dashboard runs list", () => {
  it("shows an empty state with no runs", async () => {
    serve();
    await mount();
    expect(screen.getByText("No agent runs yet")).toBeInTheDocument();
    expect(screen.getByText("Waiting for a Slack request")).toBeInTheDocument();
    expect(screen.getByText("No telemetry yet")).toBeInTheDocument();
    expect(screen.getByText("No external evidence")).toBeInTheDocument();
  });

  it("lists runs with route, age and risk score", async () => {
    serve({
      overview: makeOverview({runs: [
        makeRun({id: "r1", question: "Q one", route: "analyst", risk_score: 0, created_at: "2026-10-08T11:59:30Z"}),
        makeRun({id: "r2", question: "Q two", route: undefined, risk_score: 80, created_at: "2026-10-08T11:57:00Z"}),
        makeRun({id: "r3", question: "Q three", route: "research", risk_score: 55, created_at: "2026-10-08T09:00:00Z"}),
      ]}),
      runs: {r1: makeRunDetail({id: "r1", question: "Q one"})},
    });
    await mount();
    const rows = Object.fromEntries(screen.getAllByRole("button").filter(b => b.closest(".run-list")).map(button => [
      within(button).getByText(/^Q /).textContent, button.textContent,
    ]));
    expect(rows["Q one"]).toContain("analyst · 30s ago");
    expect(rows["Q two"]).toContain("routing · 3m ago");
    expect(rows["Q three"]).toContain("research · 3h ago");
    expect(rows["Q two"]).toContain("80");
  });

  it("never shows a negative age for a run created slightly in the future", async () => {
    serve({overview: makeOverview({runs: [makeRun({id: "r1", created_at: "2026-10-08T12:00:05Z"})]}), runs: {r1: makeRunDetail()}});
    await mount();
    expect(screen.getByText(/analyst · 0s ago/)).toBeInTheDocument();
  });

  it("selects the newest run automatically and fetches its detail", async () => {
    const {stub} = serve({
      overview: makeOverview({runs: [makeRun({id: "r1", question: "Newest"}), makeRun({id: "r2", question: "Older"})]}),
      runs: {r1: makeRunDetail({id: "r1", question: "Newest", final_answer: "Newest answer"}), r2: makeRunDetail({id: "r2"})},
    });
    await mount();
    expect(screen.getByRole("heading", {level: 2})).toHaveTextContent("Newest");
    expect(screen.getByText("Newest answer")).toBeInTheDocument();
    expect(callsTo(stub, "/api/runs/r1").length).toBeGreaterThan(0);
    expect(callsTo(stub, "/api/runs/r2")).toHaveLength(0);
    expect(screen.getByRole("button", {name: /Newest/})).toHaveClass("selected");
  });

  it("switches to another run when clicked", async () => {
    serve({
      overview: makeOverview({runs: [makeRun({id: "r1", question: "Newest"}), makeRun({id: "r2", question: "Older"})]}),
      runs: {
        r1: makeRunDetail({id: "r1", question: "Newest", final_answer: "Newest answer"}),
        r2: makeRunDetail({id: "r2", question: "Older", final_answer: "Older answer", risk_score: 80}),
      },
    });
    await mount();
    fireEvent.click(screen.getByRole("button", {name: /Older/}));
    await settle(0);
    expect(screen.getByRole("heading", {level: 2})).toHaveTextContent("Older");
    expect(screen.getByText("Older answer")).toBeInTheDocument();
    expect(screen.getByRole("button", {name: /Older/})).toHaveClass("selected");
    expect(screen.getByRole("button", {name: /Newest/})).not.toHaveClass("selected");
  });

  it("keeps the selected run through later polls even when newer runs arrive", async () => {
    const first = makeRun({id: "r1", question: "First"});
    const world = serve({overview: makeOverview({runs: [first]}), runs: {r1: makeRunDetail({id: "r1", question: "First"})}});
    await mount();
    world.state.overview = makeOverview({runs: [makeRun({id: "r2", question: "Second"}), first]});
    world.state.runs.r2 = makeRunDetail({id: "r2", question: "Second"});
    await settle(10000);
    expect(screen.getByText("Second", {selector: "b"})).toBeInTheDocument();
    expect(screen.getByRole("heading", {level: 2})).toHaveTextContent("First");
  });
});

describe("Dashboard run detail", () => {
  const detail = (overrides: Partial<RunDetail>) => serve({
    overview: makeOverview({runs: [makeRun()]}), runs: {"run-1": makeRunDetail(overrides)},
  });

  it("prefers the final answer over the draft", async () => {
    detail({draft: "draft text", final_answer: "final text"});
    await mount();
    expect(screen.getByText("final text")).toBeInTheDocument();
    expect(screen.queryByText("draft text")).not.toBeInTheDocument();
  });

  it("falls back to the draft, then to a placeholder", async () => {
    detail({draft: "draft text"});
    const {unmount} = await mount();
    expect(screen.getByText("draft text")).toBeInTheDocument();
    unmount();
    detail({});
    await mount();
    expect(screen.getByText("Agent output will appear here as the graph advances.")).toBeInTheDocument();
  });

  it("lists audit events newest first with a count", async () => {
    detail({log: [
      makeLog("Route", {sequence: 1, summary: "guidebook-first default"}),
      makeLog("Analyst", {sequence: 2, summary: "Drafted answer from 8 chunks"}),
      makeLog("Auditor", {sequence: 3, summary: "approved; risk score 0"}),
    ]});
    await mount();
    expect(screen.getByText("3 events")).toBeInTheDocument();
    const nodes = [...document.querySelectorAll(".audit-list .audit-node")].map(el => el.textContent);
    expect(nodes).toEqual(["Auditor", "Analyst", "Route"]);
    expect(screen.getByText("Drafted answer from 8 chunks")).toBeInTheDocument();
  });

  it("feeds the trace graph from the run log", async () => {
    detail({log: [makeLog("Route"), makeLog("Analyst"), makeLog("HumanReview", {status: "awaiting"})]});
    await mount();
    const review = screen.getByText("HumanReview", {selector: ".graph-node span"}).closest(".graph-node");
    expect(review).toHaveClass("waiting");
  });

  it("feeds the risk card from the run", async () => {
    detail({risk_score: 80, risk_flags: ["vendor_lock_in"], risk_breakdown: {total: 80, vendor_lock_in: 30}});
    await mount();
    expect(screen.getByText("Human review")).toBeInTheDocument();
    expect(screen.getByText("vendor lock in", {selector: ".tags span"})).toBeInTheDocument();
    expect(screen.getByText("+30")).toBeInTheDocument();
  });

  it("shows web sources as external links with their hostname", async () => {
    detail({research_findings: [
      {title: "Cloud One award", url: "https://www.usaspending.gov/award/1", excerpt: "x"},
      {title: "Solicitation", url: "https://sam.gov/opp/2", excerpt: "y"},
    ]});
    await mount();
    const link = screen.getByRole("link", {name: /Cloud One award/});
    expect(link).toHaveAttribute("href", "https://www.usaspending.gov/award/1");
    expect(link).toHaveAttribute("target", "_blank");
    expect(link).toHaveAttribute("rel", "noreferrer");
    expect(within(link).getByText("www.usaspending.gov")).toBeInTheDocument();
    expect(screen.getByText("sam.gov")).toBeInTheDocument();
  });

  it("shows citation issues and counts them with the sources in the Evidence heading", async () => {
    detail({
      research_findings: [{title: "Source", url: "https://sam.gov/opp/2", excerpt: "y"}],
      citation_issues: [
        {citation: "[Web 1]", reason: "Snippet only"},
        {citation: "human_review", reason: "Reviewer requested revision"},
      ],
    });
    await mount();
    expect(screen.getByText("Evidence").nextElementSibling).toHaveTextContent("3");
    expect(screen.getByText("Snippet only")).toBeInTheDocument();
    expect(screen.getByText("Reviewer requested revision")).toBeInTheDocument();
    expect(screen.queryByText("No external evidence")).not.toBeInTheDocument();
  });

  it("keeps showing the last good detail when a detail request fails", async () => {
    const world = serve({
      overview: makeOverview({runs: [makeRun()]}),
      runs: {"run-1": makeRunDetail({final_answer: "good answer"})},
    });
    await mount();
    world.state.runs["run-1"] = json({detail: "boom"}, 500);
    await settle(10000);
    expect(screen.getByText("good answer")).toBeInTheDocument();
    expect(screen.queryByText(/retrying automatically/)).not.toBeInTheDocument();
  });
});

describe("Dashboard document repository", () => {
  it("shows NO IMPORT until a corpus import exists", async () => {
    serve();
    await mount();
    expect(screen.getByText("NO IMPORT")).toBeInTheDocument();
    expect(screen.getByText("Upload a PDF in Slack")).toBeInTheDocument();
  });

  it("summarises the latest import", async () => {
    serve({overview: makeOverview({imports: [{
      id: "i1", archive_filename: "guidebooks.zip", archive_sha256: "x", status: "completed",
      summary: {total: 28, ready: 26, failed: 2}, created_at: "2026-10-01T00:00:00Z", updated_at: "2026-10-01T00:00:00Z",
    }]})});
    await mount();
    expect(screen.getByText("completed · 26/28")).toBeInTheDocument();
  });

  it("tolerates an import with no summary yet", async () => {
    serve({overview: makeOverview({imports: [{
      id: "i1", archive_filename: "g.zip", archive_sha256: "x", status: "running",
      created_at: "2026-10-01T00:00:00Z", updated_at: "2026-10-01T00:00:00Z",
    }]})});
    await mount();
    expect(screen.getByText("running · 0/0")).toBeInTheDocument();
  });

  it("describes recent documents", async () => {
    serve({overview: makeOverview({document_total: 3, documents: [
      makeDoc({id: "a", filename: "Current.pdf", nickname: "cur", page_count: 12, chunk_count: 40}),
      makeDoc({id: "b", filename: "Old.pdf", is_canonical: false, extraction_method: undefined, status: "ready", page_count: undefined}),
      makeDoc({id: "c", filename: "Scan.pdf", extraction_method: "ocr"}),
    ]})});
    await mount();
    const list = within(document.querySelector(".document-list") as HTMLElement);
    expect(list.getByText("cur · Current.pdf")).toBeInTheDocument();
    expect(list.getByText("12 pages · 40 vectors · native · canonical")).toBeInTheDocument();
    expect(list.getByText("? pages · 42 vectors · ready · historical")).toBeInTheDocument();
    expect(list.getByText(/· ocr · canonical/)).toBeInTheDocument();
  });

  it("shows live ingestion progress", async () => {
    serve({overview: makeOverview({ingesting: [
      makeDoc({id: "a", filename: "Big.pdf", status: "processing", progress_percent: 45, progress_label: "embedding 4/10 chunks"}),
    ]})});
    await mount();
    const bar = screen.getByRole("progressbar");
    expect(bar).toHaveAttribute("aria-valuenow", "45");
    expect(bar).toHaveAttribute("aria-valuemin", "0");
    expect(bar).toHaveAttribute("aria-valuemax", "100");
    expect(bar.firstElementChild).toHaveStyle({width: "45%"});
    expect(screen.getByText("45% · embedding 4/10 chunks")).toBeInTheDocument();
  });

  it("shows ingestion failures with their reason", async () => {
    serve({overview: makeOverview({ingesting: [
      makeDoc({id: "a", filename: "Locked.pdf", status: "failed", error: "PDF requires a password"}),
      makeDoc({id: "b", filename: "Weird.pdf", status: "failed"}),
    ]})});
    await mount();
    expect(screen.getByText("Failed: PDF requires a password")).toBeInTheDocument();
    expect(screen.getByText("Failed")).toBeInTheDocument();
    expect(screen.queryByRole("progressbar")).not.toBeInTheDocument();
  });

  it("refreshes the documents table when ingestion progress changes", async () => {
    const world = serve({overview: makeOverview({ingesting: [
      makeDoc({id: "a", status: "processing", progress_percent: 10, progress_label: "x"}),
    ]})});
    const {stub} = world;
    await mount();
    const before = callsTo(stub, "/api/documents").length;
    world.state.overview = makeOverview({ingesting: [
      makeDoc({id: "a", status: "processing", progress_percent: 60, progress_label: "x"}),
    ]});
    await settle(1500);
    expect(callsTo(stub, "/api/documents").length).toBe(before + 1);
    await settle(1500); // unchanged progress should not reload the table again
    expect(callsTo(stub, "/api/documents").length).toBe(before + 1);
  });
});

describe("Dashboard polling cadence", () => {
  const overviewCalls = (stub: ReturnType<typeof serve>["stub"]) => callsTo(stub, "/api/overview").length;

  it("polls every 10 seconds when nothing is active", async () => {
    const {stub} = serve({overview: makeOverview({runs: [makeRun({status: "completed"})]}), runs: {"run-1": makeRunDetail()}});
    await mount();
    const initial = overviewCalls(stub);
    await settle(9900);
    expect(overviewCalls(stub)).toBe(initial);
    await settle(100);
    expect(overviewCalls(stub)).toBeGreaterThan(initial);
  });

  it.each(["queued", "running", "awaiting_review"])("polls every 1.5 seconds while a run is %s", async status => {
    const {stub} = serve({overview: makeOverview({runs: [makeRun({status})]}), runs: {"run-1": makeRunDetail()}});
    await mount();
    const initial = overviewCalls(stub);
    await settle(1400);
    expect(overviewCalls(stub)).toBe(initial);
    await settle(100);
    const afterFirst = overviewCalls(stub);
    expect(afterFirst).toBeGreaterThan(initial);
    await settle(1500);
    expect(overviewCalls(stub)).toBeGreaterThan(afterFirst);
  });

  it.each(["pending", "processing"])("polls quickly while a document is %s", async status => {
    const {stub} = serve({overview: makeOverview({ingesting: [makeDoc({status})]})});
    await mount();
    const initial = overviewCalls(stub);
    await settle(1500);
    expect(overviewCalls(stub)).toBeGreaterThan(initial);
  });

  it("does not poll quickly just because a document failed", async () => {
    const {stub} = serve({overview: makeOverview({ingesting: [makeDoc({status: "failed"})]})});
    await mount();
    await settle(9000);
    expect(overviewCalls(stub)).toBe(1);
  });

  it("slows back down once the work finishes", async () => {
    const world = serve({overview: makeOverview({runs: [makeRun({status: "running"})]}), runs: {"run-1": makeRunDetail()}});
    await mount();
    world.state.overview = makeOverview({runs: [makeRun({status: "completed"})]});
    await settle(1500);
    const afterFinish = overviewCalls(world.stub);
    await settle(9000);
    expect(overviewCalls(world.stub)).toBe(afterFinish);
    await settle(1000);
    expect(overviewCalls(world.stub)).toBe(afterFinish + 1);
  });

  it("stops polling when unmounted", async () => {
    const {stub} = serve({overview: makeOverview({runs: [makeRun({status: "running"})]}), runs: {"run-1": makeRunDetail()}});
    const {unmount} = await mount();
    unmount();
    const calls = stub.mock.calls.length;
    await settle(30000);
    expect(stub.mock.calls.length).toBe(calls);
  });
});

describe("Dashboard connection errors", () => {
  it("shows a banner when the backend is down and retries after 5 seconds", async () => {
    const world = serve({overview: () => json({}, 503)});
    await mount();
    expect(screen.getByText("Backend unavailable; retrying automatically.")).toBeInTheDocument();
    expect(callsTo(world.stub, "/api/overview")).toHaveLength(1);
    await settle(4900);
    expect(callsTo(world.stub, "/api/overview")).toHaveLength(1);
    await settle(100);
    expect(callsTo(world.stub, "/api/overview")).toHaveLength(2);
  });

  it("treats a failing readiness check as the backend being down", async () => {
    serve({ready: () => json({}, 500)});
    await mount();
    expect(screen.getByText(/Backend unavailable/)).toBeInTheDocument();
  });

  it("recovers and clears the banner when the backend returns", async () => {
    const world = serve({overview: () => json({}, 503)});
    await mount();
    world.state.overview = makeOverview({mode: "live"});
    await settle(5000);
    expect(screen.queryByText(/retrying automatically/)).not.toBeInTheDocument();
    expect(screen.getByText("SYSTEM READY")).toBeInTheDocument();
  });

  it("shows the underlying message for a network failure", async () => {
    vi.stubGlobal("fetch", vi.fn(async () => { throw new TypeError("Failed to fetch"); }));
    await mount();
    expect(screen.getByText("Failed to fetch; retrying automatically.")).toBeInTheDocument();
  });

  it("uses a generic message when the failure is not an Error", async () => {
    vi.stubGlobal("fetch", vi.fn(async () => { throw "weird"; }));
    await mount();
    expect(screen.getByText("Connection failed; retrying automatically.")).toBeInTheDocument();
  });

  it("keeps showing the last data while the backend is unreachable", async () => {
    const world = serve({overview: makeOverview({runs: [makeRun({question: "Still here"})]}), runs: {"run-1": makeRunDetail({question: "Still here"})}});
    await mount();
    world.state.overview = () => json({}, 503);
    await settle(10000);
    expect(screen.getByText(/retrying automatically/)).toBeInTheDocument();
    expect(screen.getByRole("heading", {level: 2})).toHaveTextContent("Still here");
  });
});

describe("Dashboard run selection races", () => {
  it("ignores a slow detail response for a run that is no longer selected", async () => {
    let releaseFirst: (value: Response) => void = () => {};
    const slowFirst = new Promise<Response>(resolve => { releaseFirst = resolve; });
    let firstRequests = 0;
    mockFetch(url => {
      if (url.pathname === "/api/overview") return makeOverview({runs: [makeRun({id: "r1", question: "First"}), makeRun({id: "r2", question: "Second"})]});
      if (url.pathname === "/health/ready") return READY;
      // Only the very first detail request for r1 is slow; later ones answer immediately.
      if (url.pathname === "/api/runs/r1") return ++firstRequests === 1 ? slowFirst : makeRunDetail({id: "r1", question: "First"});
      if (url.pathname === "/api/runs/r2") return makeRunDetail({id: "r2", question: "Second"});
      if (url.pathname === "/api/documents") return makeDocPage([]);
    });
    await mount();
    fireEvent.click(screen.getByRole("button", {name: /Second/}));
    await settle(0);
    expect(screen.getByRole("heading", {level: 2})).toHaveTextContent("Second");
    releaseFirst(json(makeRunDetail({id: "r1", question: "First"})));
    await settle(0);
    expect(screen.getByRole("heading", {level: 2})).toHaveTextContent("Second");
  });

  it("ignores a slow detail response even when the old run answers last by a wide margin", async () => {
    let releaseFirst: (value: Response) => void = () => {};
    const slowFirst = new Promise<Response>(resolve => { releaseFirst = resolve; });
    let firstRequests = 0;
    mockFetch(url => {
      if (url.pathname === "/api/overview") return makeOverview({runs: [makeRun({id: "r1", question: "First"}), makeRun({id: "r2", question: "Second"})]});
      if (url.pathname === "/health/ready") return READY;
      if (url.pathname === "/api/runs/r1") return ++firstRequests === 1 ? slowFirst : makeRunDetail({id: "r1", question: "First"});
      if (url.pathname === "/api/runs/r2") return makeRunDetail({id: "r2", question: "Second", final_answer: "Second answer"});
      if (url.pathname === "/api/documents") return makeDocPage([]);
    });
    await mount();
    fireEvent.click(screen.getByRole("button", {name: /Second/}));
    await settle(30000); // several polls for r2 happen before r1 finally answers
    releaseFirst(json(makeRunDetail({id: "r1", question: "First", final_answer: "First answer"})));
    await settle(0);
    expect(screen.getByText("Second answer")).toBeInTheDocument();
    expect(screen.queryByText("First answer")).not.toBeInTheDocument();
  });

  it("leaves no orphaned polling loop behind when a request was in flight during the switch", async () => {
    let releaseFirst: (value: Response) => void = () => {};
    const slowFirst = new Promise<Response>(resolve => { releaseFirst = resolve; });
    let firstRequests = 0;
    const stub = mockFetch(url => {
      if (url.pathname === "/api/overview") return makeOverview({runs: [makeRun({id: "r1", question: "First"}), makeRun({id: "r2", question: "Second"})]});
      if (url.pathname === "/health/ready") return READY;
      if (url.pathname === "/api/runs/r1") return ++firstRequests === 1 ? slowFirst : makeRunDetail({id: "r1"});
      if (url.pathname === "/api/runs/r2") return makeRunDetail({id: "r2", question: "Second"});
      if (url.pathname === "/api/documents") return makeDocPage([]);
    });
    await mount();
    fireEvent.click(screen.getByRole("button", {name: /Second/}));
    await settle(0);
    releaseFirst(json(makeRunDetail({id: "r1"})));
    await settle(0);
    const baseline = callsTo(stub, "/api/overview").length;
    await settle(10000);
    expect(callsTo(stub, "/api/overview").length).toBe(baseline + 1); // r2's loop only
  });

  it("fetches the default run's detail exactly once on first load", async () => {
    const {stub} = serve({
      overview: makeOverview({runs: [makeRun({id: "r1"})]}), runs: {r1: makeRunDetail({id: "r1", final_answer: "ok"})},
    });
    await mount();
    expect(screen.getByText("ok")).toBeInTheDocument();
    expect(callsTo(stub, "/api/runs/r1")).toHaveLength(1);
  });
});
