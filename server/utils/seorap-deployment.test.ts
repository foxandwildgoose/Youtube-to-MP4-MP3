import assert from "node:assert/strict";
import { afterEach, beforeEach, test } from "node:test";
import seorapProxy from "../middleware/seorap-proxy.ts";
import { deploymentFor } from "./seorap-deployment.ts";

const originalFetch = globalThis.fetch;
const keys = [
  "VERCEL",
  "VERCEL_ENV",
  "VERCEL_URL",
  "VERCEL_PROJECT_PRODUCTION_URL",
  "SEORAP_DEPLOYMENT",
  "SEORAP_APP_ORIGIN",
  "SEORAP_PREVIEW_ALLOWED_HOSTS",
  "SEORAP_PREVIEW_ORIGINS",
];
let environment: Record<string, string | undefined>;
beforeEach(() => {
  environment = Object.fromEntries(keys.map((key) => [key, process.env[key]]));
  for (const key of keys) delete process.env[key];
});
afterEach(() => {
  for (const key of keys) {
    if (environment[key] === undefined) delete process.env[key];
    else process.env[key] = environment[key];
  }
  globalThis.fetch = originalFetch;
});
async function invoke(address: string, init: RequestInit = {}) {
  const headers = new Headers(init.headers);
  if (!headers.has("host")) headers.set("host", new URL(address).host);
  const req = new Request(address, { ...init, headers });
  let nextCalls = 0;
  const response = await seorapProxy({ url: new URL(address), req }, () => {
    nextCalls += 1;
    return new Response("platform-next", { headers: { "x-platform-next": "true" } });
  });
  assert.ok(response instanceof Response);
  return { response, nextCalls };
}
function noFetch() {
  globalThis.fetch = async () =>
    assert.fail("Hosted middleware must never fetch a backend or forward cookies");
}

test("public hosted session GET reports missing deployment rather than the reproduced false CSRF 403", async () => {
  process.env.VERCEL = "1";
  noFetch();
  const { response, nextCalls } = await invoke("https://frontend.example.com/api/v1/auth/session");
  assert.equal(response.status, 503);
  assert.equal(nextCalls, 0);
  const body = await response.json();
  assert.equal(body.error.code, "DEPLOYMENT_NOT_CONFIGURED");
  assert.equal(body.error.retryable, false);
  assert.equal(response.headers.get("cache-control"), "no-store");
  assert.equal(response.headers.has("set-cookie"), false);
});
test("every explicit hosted signal prevents loopback proxying even without an app target", async () => {
  noFetch();
  for (const [key, value] of [
    ["VERCEL", "true"],
    ["VERCEL_ENV", "production"],
    ["VERCEL_ENV", "preview"],
    ["SEORAP_DEPLOYMENT", "hosted"],
    ["SEORAP_APP_ORIGIN", ""],
  ]) {
    process.env[key] = value;
    const { response } = await invoke("https://frontend.example.com/healthz");
    assert.equal(response.status, 503);
    assert.equal((await response.json()).error.code, "DEPLOYMENT_NOT_CONFIGURED");
    delete process.env[key];
  }
});
test("configured hosted GET and HEAD hand off only root documents with 307 and no-store", async () => {
  process.env.SEORAP_APP_ORIGIN = "https://downloads.example.com:8443/";
  noFetch();
  for (const method of ["GET", "HEAD"])
    for (const path of ["/", "/index.html?source=frontend"]) {
      const { response, nextCalls } = await invoke("https://frontend.example.com" + path, {
        method,
        headers: { cookie: "fixture-session=never-forward" },
      });
      assert.equal(response.status, 307);
      assert.equal(nextCalls, 0);
      assert.equal(response.headers.get("location"), "https://downloads.example.com:8443/");
      assert.equal(response.headers.get("cache-control"), "no-store");
      assert.equal(response.headers.get("referrer-policy"), "no-referrer");
      assert.equal(response.headers.has("set-cookie"), false);
      assert.equal(await response.text(), "");
    }
});
test("configured hosted API, SSE, file ranges, mutations and health never contact any backend", async () => {
  process.env.SEORAP_APP_ORIGIN = "https://downloads.example.com";
  noFetch();
  for (const [path, method] of [
    ["/api/v1", "GET"],
    ["/api/v1/jobs/fixture/events", "GET"],
    ["/api/v1/jobs/fixture/file", "GET"],
    ["/api/v1/jobs/fixture/file", "HEAD"],
    ["/api/v1/jobs", "POST"],
    ["/healthz", "GET"],
  ]) {
    const { response } = await invoke("https://frontend.example.com" + path, {
      method,
      headers: {
        cookie: "fixture=never-forward",
        range: "bytes=0-99",
        "sec-fetch-site": "cross-site",
      },
    });
    assert.equal(response.status, 503);
    const body = await response.json();
    assert.equal(body.error.code, "APP_HANDOFF_REQUIRED");
    assert.equal(body.error.retryable, false);
    assert.equal(response.headers.has("set-cookie"), false);
    assert.equal(response.headers.has("location"), false);
  }
});
test("missing and invalid targets leave the root available for an actionable configuration page", async () => {
  process.env.VERCEL = "1";
  noFetch();
  for (const target of [undefined, "http://downloads.example.com", "https://127.0.0.1"]) {
    if (target === undefined) delete process.env.SEORAP_APP_ORIGIN;
    else process.env.SEORAP_APP_ORIGIN = target;
    const { response, nextCalls } = await invoke("https://frontend.example.com/");
    assert.equal(response.status, 200);
    assert.equal(nextCalls, 1);
    assert.equal(await response.text(), "platform-next");
  }
});
test("hosted handoff preserves Grok install query, PWA/platform auth and other unowned routes", async () => {
  process.env.SEORAP_APP_ORIGIN = "https://downloads.example.com";
  noFetch();
  for (const path of [
    "/?install=1&platform=ios",
    "/?install=true&platform=IOS",
    "/__grok/manifest.webmanifest",
    "/__grok/install/styles.css",
    "/api/auth/session",
    "/api/auth/sign-in",
    "/auth/popup",
    "/assets/app.js",
    "/api/v10/jobs",
  ]) {
    const { response, nextCalls } = await invoke("https://frontend.example.com" + path);
    assert.equal(response.status, 200);
    assert.equal(nextCalls, 1);
    assert.equal(response.headers.get("x-platform-next"), "true");
  }
});
test("invalid HTTPS targets, userinfo, path/query/hash, controls, local and reserved addresses are rejected", async () => {
  noFetch();
  const targets = [
    "http://downloads.example.com",
    "//downloads.example.com",
    "https://user:fixture@downloads.example.com",
    "https://@downloads.example.com",
    "https://downloads.example.com/path",
    "https://downloads.example.com/a/..",
    "https://downloads.example.com/?q=1",
    "https://downloads.example.com/#hash",
    "https://downloads.example.com\\evil",
    "https://downloads.example.com\n",
    "https://downloads.example.com:0",
    "https://localhost",
    "https://sub.localhost",
    "https://backend.local",
    "https://service.internal",
    "https://metadata.google.internal",
    "https://backend",
    "https://0.0.0.0",
    "https://127.0.0.1",
    "https://127.1",
    "https://2130706433",
    "https://10.0.0.1",
    "https://100.64.0.1",
    "https://169.254.169.254",
    "https://172.16.0.1",
    "https://192.168.1.1",
    "https://192.0.2.1",
    "https://198.18.0.1",
    "https://198.51.100.1",
    "https://203.0.113.1",
    "https://224.0.0.1",
    "https://[::1]",
    "https://[::ffff:127.0.0.1]",
    "https://[fc00::1]",
    "https://[fe80::1]",
    "https://[2001:db8::1]",
    "https://[2002:7f00:1::]",
  ];
  for (const target of targets) {
    process.env.SEORAP_APP_ORIGIN = target;
    const { response } = await invoke("https://frontend.example.com/api/v1/auth/session");
    assert.equal(response.status, 503);
    assert.equal((await response.json()).error.code, "DEPLOYMENT_NOT_CONFIGURED", target);
  }
});
test("same frontend and configured Vercel aliases cannot create redirect loops even across ports", async () => {
  noFetch();
  process.env.VERCEL_URL = "preview-abc.vercel.app";
  process.env.VERCEL_PROJECT_PRODUCTION_URL = "production.vercel.app";
  for (const target of [
    "https://frontend.example.com",
    "https://frontend.example.com:8443",
    "https://frontend.example.com.",
    "https://preview-abc.vercel.app",
    "https://production.vercel.app",
  ]) {
    process.env.SEORAP_APP_ORIGIN = target;
    const { response } = await invoke("https://frontend.example.com/api/v1/auth/session");
    assert.equal((await response.json()).error.code, "DEPLOYMENT_NOT_CONFIGURED");
  }
  process.env.SEORAP_APP_ORIGIN = "https://public-alias.example.com";
  const { response } = await invoke("http://127.0.0.1/api/v1/auth/session", {
    headers: { host: "public-alias.example.com" },
  });
  assert.equal((await response.json()).error.code, "DEPLOYMENT_NOT_CONFIGURED");
});
test("untrusted forwarded host neither authorizes a target nor selects a redirect", async () => {
  process.env.SEORAP_APP_ORIGIN = "https://downloads.example.com";
  noFetch();
  const { response } = await invoke("https://frontend.example.com/", {
    headers: { "x-forwarded-host": "downloads.example.com", "x-forwarded-proto": "http" },
  });
  assert.equal(response.status, 307);
  assert.equal(response.headers.get("location"), "https://downloads.example.com/");
  assert.equal(
    deploymentFor(new Request("https://frontend.example.com/"), {
      SEORAP_APP_ORIGIN: "https://[2606:4700:4700::1111]",
    }).appOrigin,
    "https://[2606:4700:4700::1111]",
  );
});
test("local preview validates incoming security before rewriting and keeps platform auth separate", async () => {
  let fetches = 0;
  globalThis.fetch = async (input, init) => {
    fetches += 1;
    assert.equal(input, "http://127.0.0.1:8000/api/v1/jobs?limit=20");
    const headers = new Headers(init?.headers);
    assert.equal(headers.get("host"), "127.0.0.1:8000");
    assert.equal(headers.get("origin"), "http://127.0.0.1:8000");
    assert.equal(headers.get("cookie"), "fixture=local-only");
    assert.equal(headers.has("x-forwarded-host"), false);
    assert.equal(headers.has("x-forwarded-proto"), false);
    assert.equal(init?.body instanceof Uint8Array, true);
    return new Response("{}", {
      status: 202,
      headers: { "set-cookie": "fixture=local-response; HttpOnly" },
    });
  };
  const good = await invoke("http://127.0.0.1:8080/api/v1/jobs?limit=20", {
    method: "POST",
    body: "{}",
    headers: {
      origin: "http://127.0.0.1:8080",
      cookie: "fixture=local-only",
      "x-forwarded-host": "evil.example.com",
      "x-forwarded-proto": "https",
    },
  });
  assert.equal(good.response.status, 202);
  assert.equal(fetches, 1);
  assert.ok(good.response.headers.get("set-cookie"));
  const rejectedHeaders: HeadersInit[] = [
    { origin: "https://evil.example.com" },
    { host: "evil.example.com", origin: "http://127.0.0.1:8080" },
    {},
  ];
  for (const headers of rejectedHeaders) {
    const bad = await invoke("http://127.0.0.1:8080/api/v1/jobs", {
      method: "POST",
      body: "{}",
      headers,
    });
    assert.equal(bad.response.status, 403);
    assert.equal((await bad.response.json()).error.code, "CSRF_FAILED");
  }
  const platform = await invoke("http://127.0.0.1:8080/api/auth/session");
  assert.equal(platform.nextCalls, 1);
  assert.equal(fetches, 1);
});
test("local file ranges preserve streamed bytes and range headers without buffering", async () => {
  let enqueue!: ReadableStreamDefaultController<Uint8Array>;
  const body = new ReadableStream<Uint8Array>({
    start(controller) {
      enqueue = controller;
      controller.enqueue(new Uint8Array([1, 2]));
    },
  });
  globalThis.fetch = async (_input, init) => {
    assert.equal(new Headers(init?.headers).get("range"), "bytes=1-4");
    return new Response(body, {
      status: 206,
      headers: {
        "content-range": "bytes 1-4/10000000000",
        "content-length": "4",
        "accept-ranges": "bytes",
        "content-type": "video/mp4",
      },
    });
  };
  const { response } = await invoke("http://127.0.0.1:8080/api/v1/jobs/fixture/file", {
    headers: { range: "bytes=1-4" },
  });
  assert.equal(response.status, 206);
  assert.equal(response.headers.get("content-range"), "bytes 1-4/10000000000");
  const reader = response.body!.getReader();
  assert.deepEqual((await reader.read()).value, new Uint8Array([1, 2]));
  enqueue.enqueue(new Uint8Array([3, 4]));
  enqueue.close();
  assert.deepEqual((await reader.read()).value, new Uint8Array([3, 4]));
  assert.equal((await reader.read()).done, true);
});
test("local SSE stays streaming and forwards browser disconnect after middleware returns", async () => {
  let upstreamSignal: AbortSignal | null | undefined;
  let enqueue!: ReadableStreamDefaultController<Uint8Array>;
  const body = new ReadableStream<Uint8Array>({
    start(controller) {
      enqueue = controller;
      controller.enqueue(new TextEncoder().encode(": heartbeat\n\n"));
    },
  });
  globalThis.fetch = async (_input, init) => {
    upstreamSignal = init?.signal;
    return new Response(body, {
      headers: { "content-type": "text/event-stream", "cache-control": "no-cache" },
    });
  };
  const disconnect = new AbortController();
  const { response } = await invoke("http://127.0.0.1:8080/api/v1/jobs/fixture/events", {
    signal: disconnect.signal,
  });
  assert.equal(response.headers.get("content-type"), "text/event-stream");
  const reader = response.body!.getReader();
  assert.match(new TextDecoder().decode((await reader.read()).value), /heartbeat/);
  disconnect.abort();
  assert.equal(upstreamSignal?.aborted, true);
  enqueue.close();
  await reader.cancel();
});

test("local middleware still rejects actual oversized request bytes before any upstream fetch", async () => {
  noFetch();
  const { response } = await invoke("http://127.0.0.1:8080/api/v1/analyses", {
    method: "POST",
    body: "x".repeat(65537),
    headers: { origin: "http://127.0.0.1:8080", "content-length": "1" },
  });
  assert.equal(response.status, 413);
  assert.equal((await response.json()).error.code, "LIMIT_EXCEEDED");
});
