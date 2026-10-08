import {act, fireEvent, render, screen, waitFor, within} from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import {describe, expect, it} from "vitest";
import {DocumentsTable} from "@/components/documents-table";
import {callsTo, json, mockFetch} from "./api";
import {makeDoc, makeDocPage} from "./fixtures";

const API = "http://api.test";

function docs(count: number) {
  return Array.from({length: count}, (_, index) => makeDoc({id: `doc-${index + 1}`, filename: `Guide ${index + 1}.pdf`}));
}

/** Serve `all` through the real limit/offset/q contract of GET /api/documents. */
function serve(all = docs(25)) {
  return mockFetch(url => {
    if (url.pathname !== "/api/documents") return undefined;
    const limit = Number(url.searchParams.get("limit"));
    const offset = Number(url.searchParams.get("offset"));
    const q = url.searchParams.get("q")?.toLowerCase();
    const matching = q ? all.filter(item => item.filename.toLowerCase().includes(q)) : all;
    return makeDocPage(matching.slice(offset, offset + limit), {total: matching.length, limit, offset});
  });
}

function requestedParams(stub: ReturnType<typeof serve>) {
  return callsTo(stub, "/api/documents").map(([input]) => Object.fromEntries(new URL(String(input)).searchParams));
}

function renderTable(refreshKey = "k1") {
  return render(<DocumentsTable api={API} refreshKey={refreshKey}/>);
}

describe("DocumentsTable loading", () => {
  it("shows a loading row, then the documents", async () => {
    serve(docs(3));
    renderTable();
    expect(screen.getByText("Loading…")).toBeInTheDocument();
    expect(await screen.findByText("Guide 1.pdf")).toBeInTheDocument();
    expect(screen.queryByText("Loading…")).not.toBeInTheDocument();
    expect(screen.getByText("Documents · 3")).toBeInTheDocument();
  });

  it("requests the first page without a query and disables caching", async () => {
    const stub = serve(docs(3));
    renderTable();
    await screen.findByText("Guide 1.pdf");
    expect(requestedParams(stub)).toEqual([{limit: "10", offset: "0"}]);
    expect(String(stub.mock.calls[0][0])).toMatch(/^http:\/\/api\.test\/api\/documents\?/);
    expect(stub.mock.calls[0][1]).toMatchObject({cache: "no-store"});
  });

  it("shows an empty state", async () => {
    serve([]);
    renderTable();
    expect(await screen.findByText(/No documents yet/)).toBeInTheDocument();
    expect(screen.getByText("0–0 of 0")).toBeInTheDocument();
  });

  it("shows a retry message when the API returns an error", async () => {
    mockFetch(() => json({}, 500));
    renderTable();
    expect(await screen.findByText("Documents unavailable; retrying…")).toBeInTheDocument();
  });

  it("shows a retry message when the network fails", async () => {
    mockFetch(() => { throw new Error("offline"); });
    renderTable();
    expect(await screen.findByText("Documents unavailable; retrying…")).toBeInTheDocument();
  });

  it("reloads when the refresh key changes", async () => {
    const stub = serve(docs(2));
    const {rerender} = renderTable("a");
    await screen.findByText("Guide 1.pdf");
    rerender(<DocumentsTable api={API} refreshKey="a"/>);
    expect(callsTo(stub, "/api/documents")).toHaveLength(1);
    rerender(<DocumentsTable api={API} refreshKey="b"/>);
    await waitFor(() => expect(callsTo(stub, "/api/documents")).toHaveLength(2));
  });
});

describe("DocumentsTable rows", () => {
  function rowFor(filename: string): HTMLElement {
    return screen.getByText(filename).closest("tr") as HTMLElement;
  }

  it("shows pages, chunks and origin", async () => {
    serve([
      makeDoc({id: "a", filename: "Imported.pdf", page_count: 12, chunk_count: 42}),
      makeDoc({id: "b", filename: "Uploaded.pdf", channel_ids: ["C1", "C2"], page_count: undefined, chunk_count: 0}),
    ]);
    renderTable();
    await screen.findByText("Imported.pdf");

    const imported = within(rowFor("Imported.pdf"));
    expect(imported.getByText("12")).toBeInTheDocument();
    expect(imported.getByText("42")).toBeInTheDocument();
    expect(imported.getByText("Import")).toHaveAttribute("title", "Imported from the guidebook archive");

    const uploaded = within(rowFor("Uploaded.pdf"));
    expect(uploaded.getAllByText("–")).toHaveLength(2); // unknown page count and zero chunks
    expect(uploaded.getByText("Slack upload")).toHaveAttribute("title", "Uploaded in Slack channel(s): C1, C2");
  });

  it("labels canonical, historical, failed and in-progress documents", async () => {
    serve([
      makeDoc({id: "a", filename: "Current.pdf"}),
      makeDoc({id: "b", filename: "Old.pdf", is_canonical: false}),
      makeDoc({id: "c", filename: "Broken.pdf", status: "failed", error: "PDF requires a password"}),
      makeDoc({id: "d", filename: "Busy.pdf", status: "processing", progress_percent: 40, progress_label: "embedding 4/10 chunks"}),
    ]);
    renderTable();
    await screen.findByText("Current.pdf");
    expect(within(rowFor("Current.pdf")).getByText("ready")).toHaveClass("pill", "ready");
    expect(within(rowFor("Old.pdf")).getByText("historical")).toHaveClass("pill", "ready");
    const failed = within(rowFor("Broken.pdf")).getByText("failed");
    expect(failed).toHaveClass("failed");
    expect(failed).toHaveAttribute("title", "PDF requires a password");
    expect(within(rowFor("Busy.pdf")).getByText("40% · embedding 4/10 chunks")).toHaveClass("working");
  });

  it("shows the filename as a tooltip for truncated names", async () => {
    serve([makeDoc({filename: "A very long guidebook title.pdf"})]);
    renderTable();
    expect(await screen.findByText("A very long guidebook title.pdf")).toHaveAttribute("title", "A very long guidebook title.pdf");
  });
});

describe("DocumentsTable paging", () => {
  it("pages forward and back through the results", async () => {
    const stub = serve(docs(25));
    const user = userEvent.setup();
    renderTable();
    await screen.findByText("Guide 1.pdf");

    const previous = screen.getByLabelText("Previous page");
    const next = screen.getByLabelText("Next page");
    expect(screen.getByText("1–10 of 25")).toBeInTheDocument();
    expect(previous).toBeDisabled();
    expect(next).toBeEnabled();

    await user.click(next);
    expect(await screen.findByText("Guide 11.pdf")).toBeInTheDocument();
    expect(screen.getByText("11–20 of 25")).toBeInTheDocument();
    expect(requestedParams(stub).at(-1)).toEqual({limit: "10", offset: "10"});

    await user.click(next);
    expect(await screen.findByText("Guide 25.pdf")).toBeInTheDocument();
    expect(screen.getByText("21–25 of 25")).toBeInTheDocument();
    expect(next).toBeDisabled();

    await user.click(previous);
    expect(await screen.findByText("Guide 11.pdf")).toBeInTheDocument();
  });

  it("disables both buttons when everything fits on one page", async () => {
    serve(docs(10));
    renderTable();
    await screen.findByText("Guide 1.pdf");
    expect(screen.getByLabelText("Previous page")).toBeDisabled();
    expect(screen.getByLabelText("Next page")).toBeDisabled();
    expect(screen.getByText("1–10 of 10")).toBeInTheDocument();
  });

  it("steps back when the current page no longer exists", async () => {
    // e.g. documents were removed while the user was on page 2
    let remaining = docs(15);
    const stub = mockFetch(url => {
      const offset = Number(url.searchParams.get("offset"));
      return makeDocPage(remaining.slice(offset, offset + 10), {total: remaining.length, offset});
    });
    const user = userEvent.setup();
    const {rerender} = renderTable("a");
    await screen.findByText("Guide 1.pdf");
    await user.click(screen.getByLabelText("Next page"));
    await screen.findByText("Guide 11.pdf");

    remaining = docs(5);
    rerender(<DocumentsTable api={API} refreshKey="b"/>);
    expect(await screen.findByText("Guide 1.pdf")).toBeInTheDocument();
    expect(screen.getByText("1–5 of 5")).toBeInTheDocument();
    expect(requestedParams(stub).map(params => params.offset)).toContain("10");
  });
});

describe("DocumentsTable search", () => {
  it("waits for typing to pause, then searches from the first page", async () => {
    const stub = serve(docs(25));
    const user = userEvent.setup();
    renderTable();
    await screen.findByText("Guide 1.pdf");
    await user.click(screen.getByLabelText("Next page"));
    await screen.findByText("Guide 11.pdf");
    const before = callsTo(stub, "/api/documents").length;

    fireEvent.change(screen.getByPlaceholderText("Search name or nickname"), {target: {value: "  guide 2  "}});
    expect(callsTo(stub, "/api/documents")).toHaveLength(before); // debounced

    await waitFor(() => expect(requestedParams(stub).at(-1)).toEqual({limit: "10", offset: "0", q: "guide 2"}));
    expect(await screen.findByText("Guide 2.pdf")).toBeInTheDocument();
    expect(screen.getByText("Guide 25.pdf")).toBeInTheDocument();
    expect(screen.queryByText("Guide 3.pdf")).not.toBeInTheDocument();
  });

  it("only sends the last value when typing quickly", async () => {
    const stub = serve(docs(25));
    renderTable();
    await screen.findByText("Guide 1.pdf");
    const input = screen.getByPlaceholderText("Search name or nickname");
    fireEvent.change(input, {target: {value: "g"}});
    fireEvent.change(input, {target: {value: "gu"}});
    fireEvent.change(input, {target: {value: "guide 7"}});
    await waitFor(() => expect(requestedParams(stub).at(-1)).toMatchObject({q: "guide 7"}));
    expect(requestedParams(stub).filter(params => "q" in params)).toHaveLength(1);
  });

  it("explains when nothing matches", async () => {
    serve(docs(5));
    renderTable();
    await screen.findByText("Guide 1.pdf");
    fireEvent.change(screen.getByPlaceholderText("Search name or nickname"), {target: {value: "zzz"}});
    expect(await screen.findByText("No documents match that search")).toBeInTheDocument();
  });

  it("dropping the search term returns to the full list", async () => {
    const stub = serve(docs(5));
    renderTable();
    await screen.findByText("Guide 1.pdf");
    const input = screen.getByPlaceholderText("Search name or nickname");
    fireEvent.change(input, {target: {value: "guide 2"}});
    await screen.findByText("Documents · 1");
    fireEvent.change(input, {target: {value: ""}});
    await screen.findByText("Documents · 5");
    expect(requestedParams(stub).at(-1)).toEqual({limit: "10", offset: "0"});
  });
});

describe("DocumentsTable nicknames", () => {
  function nicknameServer(save: (body: unknown) => Response | undefined = () => undefined) {
    const saved: unknown[] = [];
    const stub = mockFetch((url, init) => {
      if (url.pathname === "/api/documents") {
        return makeDocPage([makeDoc({nickname: "cloud book"}), makeDoc({id: "doc-2", filename: "Other.pdf"})]);
      }
      if (url.pathname.endsWith("/nickname")) {
        const body = JSON.parse(String(init?.body));
        saved.push({path: url.pathname, method: init?.method, headers: init?.headers, body});
        return save(body) ?? json({id: "doc-1", nickname: body.nickname});
      }
    });
    return {stub, saved};
  }

  async function startEditing(user: ReturnType<typeof userEvent.setup>, label: string | RegExp = "cloud book") {
    await user.click(await screen.findByRole("button", {name: label}));
    return screen.getByPlaceholderText("e.g. cloud book");
  }

  it("shows existing nicknames and a prompt where there is none", async () => {
    nicknameServer();
    renderTable();
    expect(await screen.findByRole("button", {name: "cloud book"})).toBeInTheDocument();
    expect(screen.getByRole("button", {name: "add nickname"})).toBeInTheDocument();
  });

  it("opens an editor prefilled with the current nickname", async () => {
    nicknameServer();
    const user = userEvent.setup();
    renderTable();
    const input = await startEditing(user);
    expect(input).toHaveValue("cloud book");
    expect(input).toHaveFocus();
    expect(input).toHaveAttribute("maxlength", "40");
  });

  it("saves via the API, closes the editor and reloads the list", async () => {
    const {stub, saved} = nicknameServer();
    const user = userEvent.setup();
    renderTable();
    const input = await startEditing(user);
    const loadsBefore = callsTo(stub, "/api/documents").length;

    await user.clear(input);
    await user.type(input, "  cloud guide ");
    await user.click(screen.getByRole("button", {name: "Save"}));

    await waitFor(() => expect(screen.queryByPlaceholderText("e.g. cloud book")).not.toBeInTheDocument());
    expect(saved).toEqual([{
      path: "/api/documents/doc-1/nickname", method: "POST",
      headers: {"Content-Type": "application/json"}, body: {nickname: "cloud guide"},
    }]);
    await waitFor(() => expect(callsTo(stub, "/api/documents").length).toBe(loadsBefore + 1));
  });

  it("saves with Enter", async () => {
    const {saved} = nicknameServer();
    const user = userEvent.setup();
    renderTable();
    const input = await startEditing(user);
    await user.clear(input);
    await user.type(input, "new name{Enter}");
    await waitFor(() => expect(saved).toHaveLength(1));
    expect(saved[0]).toMatchObject({body: {nickname: "new name"}});
  });

  it("sends null to clear a nickname", async () => {
    const {saved} = nicknameServer();
    const user = userEvent.setup();
    renderTable();
    const input = await startEditing(user);
    await user.clear(input);
    await user.type(input, "   {Enter}");
    await waitFor(() => expect(saved).toHaveLength(1));
    expect(saved[0]).toMatchObject({body: {nickname: null}});
  });

  it("cancels with Escape without calling the API", async () => {
    const {saved} = nicknameServer();
    const user = userEvent.setup();
    renderTable();
    const input = await startEditing(user);
    await user.type(input, "xyz{Escape}");
    expect(screen.queryByPlaceholderText("e.g. cloud book")).not.toBeInTheDocument();
    expect(saved).toEqual([]);
    expect(screen.getByRole("button", {name: "cloud book"})).toBeInTheDocument();
  });

  it("restores the saved value when editing is reopened after cancelling", async () => {
    nicknameServer();
    const user = userEvent.setup();
    renderTable();
    const input = await startEditing(user);
    await user.type(input, " junk{Escape}");
    expect(await startEditing(user)).toHaveValue("cloud book");
  });

  it("shows a server message for a rejected nickname and keeps the editor open", async () => {
    nicknameServer(() => json({detail: "Nickname is already used by another document"}, 409));
    const user = userEvent.setup();
    renderTable();
    await startEditing(user);
    await user.click(screen.getByRole("button", {name: "Save"}));
    expect(await screen.findByText("Nickname is already used by another document")).toHaveClass("field-error");
    expect(screen.getByPlaceholderText("e.g. cloud book")).toBeInTheDocument();
  });

  it("unwraps validation errors from FastAPI", async () => {
    nicknameServer(() => json({detail: [{msg: "Value error, Nickname must be 2-40 characters"}]}, 422));
    const user = userEvent.setup();
    renderTable();
    await startEditing(user);
    await user.click(screen.getByRole("button", {name: "Save"}));
    expect(await screen.findByText("Nickname must be 2-40 characters")).toBeInTheDocument();
  });

  it("falls back to a generic message when the error body is not JSON", async () => {
    nicknameServer(() => new Response("Bad gateway", {status: 502}));
    const user = userEvent.setup();
    renderTable();
    await startEditing(user);
    await user.click(screen.getByRole("button", {name: "Save"}));
    expect(await screen.findByText("Could not save")).toBeInTheDocument();
  });

  it("clears a previous error after a successful save", async () => {
    let attempts = 0;
    nicknameServer(() => (++attempts === 1 ? json({detail: "Nope"}, 409) : undefined));
    const user = userEvent.setup();
    renderTable();
    await startEditing(user);
    await user.click(screen.getByRole("button", {name: "Save"}));
    await screen.findByText("Nope");
    await user.click(screen.getByRole("button", {name: "Save"}));
    await waitFor(() => expect(screen.queryByText("Nope")).not.toBeInTheDocument());
  });
});

describe("DocumentsTable cleanup", () => {
  it("does not misbehave when unmounted with a pending search debounce", async () => {
    const stub = serve(docs(3));
    const {unmount} = renderTable();
    await screen.findByText("Guide 1.pdf");
    fireEvent.change(screen.getByPlaceholderText("Search name or nickname"), {target: {value: "g"}});
    unmount();
    await act(async () => { await new Promise(resolve => setTimeout(resolve, 400)); });
    expect(callsTo(stub, "/api/documents")).toHaveLength(1);
  });
});
