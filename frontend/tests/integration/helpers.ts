import { vi } from "vitest";

/**
 * A fake API for integration tests: the real `api` client runs, and only
 * `fetch` is replaced. Nothing here touches the network.
 */

export const API = "http://localhost:8000";

type Reply = { status?: number; body?: unknown } | (() => { status?: number; body?: unknown });

export interface RecordedCall {
  method: string;
  path: string;
  body: unknown;
}

/** Routes are keyed `"METHOD /path"`. An unrouted request fails the test loudly. */
export function mockApi(routes: Record<string, Reply>) {
  const calls: RecordedCall[] = [];
  const fetchMock = vi.fn(async (input: RequestInfo | URL, init?: RequestInit) => {
    const url = String(input);
    const method = init?.method ?? "GET";
    const path = url.startsWith(API) ? url.slice(API.length) : url;
    calls.push({ method, path, body: typeof init?.body === "string" ? JSON.parse(init.body) : undefined });
    const route = routes[`${method} ${path}`];
    if (!route) throw new Error(`Unexpected request in test: ${method} ${path}`);
    const { status = 200, body = null } = typeof route === "function" ? route() : route;
    return new Response(JSON.stringify(body), { status, headers: { "Content-Type": "application/json" } });
  });
  vi.stubGlobal("fetch", fetchMock);
  return {
    calls,
    callsTo: (key: string) => calls.filter((c) => `${c.method} ${c.path}` === key),
  };
}

/** The API unreachable: `fetch` itself rejects, as it does when the server is down. */
export function mockApiDown() {
  vi.stubGlobal("fetch", vi.fn().mockRejectedValue(new TypeError("Failed to fetch")));
}

/** The API's error envelope. */
export const apiError = (status: number, message: string, code = "error") => ({
  status,
  body: { error: { code, message, details: {} } },
});

/** Replaces `window.location` so full-page navigations can be observed instead of performed. */
export function stubNavigation() {
  const assign = vi.fn();
  vi.stubGlobal("location", { href: "http://localhost:3000/", origin: "http://localhost:3000", assign });
  return assign;
}
