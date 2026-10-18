/**
 * Same-origin bridge for the compiled preview. Forwards /api and /healthz to
 * the local FastAPI process. A missing process becomes 503, which the screen
 * shows as "Backend not connected". This does not publish the API.
 */

interface ProxyEvent {
  url: URL;
  req: Request;
}

const TARGET = "http://127.0.0.1:8000";

export default async function seorapProxy(event: ProxyEvent, next: () => unknown | Promise<unknown>): Promise<unknown> {
  const path = event.url.pathname;
  if (path !== "/healthz" && !path.startsWith("/api/")) return next();

  const incoming = event.req;
  const method = (incoming.method || "GET").toUpperCase();
  const headers = new Headers(incoming.headers);
  headers.set("host", "127.0.0.1:8000");
  headers.set("origin", "http://127.0.0.1:8000");
  headers.delete("content-length");

  const init: RequestInit = { method, headers, redirect: "manual" };
  if (method !== "GET" && method !== "HEAD") {
    init.body = await incoming.arrayBuffer();
  }

  try {
    const response = await fetch(TARGET + path + event.url.search, init);
    const out = new Headers();
    response.headers.forEach((value, key) => {
      if (key.toLowerCase() === "set-cookie") return;
      out.set(key, value);
    });
    const cookies = typeof response.headers.getSetCookie === "function" ? response.headers.getSetCookie() : [];
    for (const cookie of cookies) out.append("set-cookie", cookie);
    return new Response(response.body, { status: response.status, headers: out });
  } catch {
    return new Response(
      JSON.stringify({
        error: {
          code: "WORKER_UNAVAILABLE",
          message: "Backend not connected",
          retryable: true,
          action: "Start the local API.",
        },
      }),
      { status: 503, headers: { "content-type": "application/json; charset=utf-8" } },
    );
  }
}
