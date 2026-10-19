#!/usr/bin/env node
/** Exercise the generated Vercel function itself, without the Vite preview bridge. */
import assert from "node:assert/strict";
import { resolve } from "node:path";
import { pathToFileURL } from "node:url";

const root = resolve(import.meta.dirname, "..");
const origin = "https://youtube-to-mp-4-mp-3.vercel.app";
const target = "https://conversion.example.com:18443";
const keys = [
  "VERCEL",
  "VERCEL_ENV",
  "VERCEL_URL",
  "VERCEL_PROJECT_PRODUCTION_URL",
  "SEORAP_DEPLOYMENT",
  "SEORAP_APP_ORIGIN",
];
const saved = Object.fromEntries(keys.map((key) => [key, process.env[key]]));
const originalFetch = globalThis.fetch;
let checks = 0;
try {
  for (const key of keys) delete process.env[key];
  process.env.VERCEL = "1";
  process.env.VERCEL_ENV = "production";
  process.env.VERCEL_PROJECT_PRODUCTION_URL = new URL(origin).hostname;
  // Hosted routing must not attempt loopback, remote API or media requests.
  globalThis.fetch = async () => assert.fail("Unexpected outbound fetch from the hosted function");
  const { default: runtime } = await import(
    pathToFileURL(resolve(root, ".vercel/output/functions/__server.func/index.mjs")).href
  );
  assert.equal(typeof runtime.fetch, "function");
  const request = (path, method = "GET") =>
    runtime.fetch(new Request(origin + path, { method, headers: { host: new URL(origin).host } }), {
      waitUntil() {},
    });

  let response = await request("/api/v1/auth/session");
  assert.equal(response.status, 503);
  assert.equal((await response.json()).error.code, "DEPLOYMENT_NOT_CONFIGURED");
  assert.equal(response.headers.get("cache-control"), "no-store");
  checks++;

  response = await request("/");
  assert.equal(response.status, 200);
  assert.ok((await response.text()).includes("서랍"));
  checks++;

  response = await request("/healthz");
  assert.equal(response.status, 503);
  checks++;

  process.env.SEORAP_APP_ORIGIN = target;
  for (const method of ["GET", "HEAD"]) {
    response = await request("/", method);
    assert.equal(response.status, 307);
    assert.equal(response.headers.get("location"), target + "/");
    assert.equal(response.headers.get("cache-control"), "no-store");
    assert.equal(response.headers.get("referrer-policy"), "no-referrer");
    assert.equal(response.headers.has("set-cookie"), false);
    checks++;
  }
  response = await request("/api/v1/jobs/fixture/file");
  assert.equal(response.status, 503);
  assert.equal((await response.json()).error.code, "APP_HANDOFF_REQUIRED");
  checks++;

  response = await request("/?install=1&platform=ios");
  assert.equal(response.status, 200);
  assert.equal(response.headers.has("location"), false);
  assert.ok((await response.text()).includes("Home Screen"));
  checks++;

  process.env.SEORAP_APP_ORIGIN = origin;
  response = await request("/api/v1/auth/session");
  assert.equal(response.status, 503);
  assert.equal((await response.json()).error.code, "DEPLOYMENT_NOT_CONFIGURED");
  checks++;
  console.log(
    JSON.stringify({
      generatedVercelFunction: "passed",
      checks,
      outboundRequests: 0,
      liveYouTube: "not run",
    }),
  );
} finally {
  globalThis.fetch = originalFetch;
  for (const key of keys) {
    if (saved[key] === undefined) delete process.env[key];
    else process.env[key] = saved[key];
  }
}
