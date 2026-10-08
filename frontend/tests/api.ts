import {vi} from "vitest";

export function json(body: unknown, status = 200): Response {
  return new Response(JSON.stringify(body), {status, headers: {"Content-Type": "application/json"}});
}

type Handler = (url: URL, init?: RequestInit) => unknown | Promise<unknown>;

/**
 * Stub global fetch. A handler may return a Response, a plain object (sent as 200 JSON),
 * or undefined (a 404, so a forgotten route fails loudly rather than hanging).
 */
export function mockFetch(handler: Handler) {
  const stub = vi.fn(async (input: RequestInfo | URL, init?: RequestInit) => {
    const result = await handler(new URL(String(input)), init);
    if (result instanceof Response) return result;
    return result === undefined ? json({detail: "unmocked route"}, 404) : json(result);
  });
  vi.stubGlobal("fetch", stub);
  return stub;
}

export function callsTo(stub: ReturnType<typeof vi.fn>, path: string) {
  return stub.mock.calls.filter(([input]) => new URL(String(input)).pathname === path);
}
