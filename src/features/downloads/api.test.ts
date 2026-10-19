import assert from "node:assert/strict";
import { afterEach, test } from "node:test";
import { api, ApiError, requestJson } from "./api.ts";
const originalFetch = globalThis.fetch;
afterEach(() => {
  globalThis.fetch = originalFetch;
});
const expectError = async (promise: Promise<unknown>, code: string, status: number | null) => {
  await assert.rejects(
    promise,
    (error: unknown) => error instanceof ApiError && error.code === code && error.status === status,
  );
};
test("FE-05 HTML 502 retains HTTP and safe request context without exposing gateway HTML", async () => {
  globalThis.fetch = async () =>
    new Response("<html>secret internal proxy path</html>", { status: 502 });
  await assert.rejects(
    requestJson("/api/v1/jobs?search=private", {}, undefined, { retries: 0 }),
    (error: unknown) => {
      assert.ok(error instanceof ApiError);
      assert.equal(error.status, 502);
      assert.equal(error.code, "HTTP_502");
      assert.equal(error.context.path, "/api/v1/jobs");
      assert.equal(error.message.includes("secret"), false);
      return true;
    },
  );
});
test("FE-05 JSON 429 retains cooldown envelope and Retry-After header precedence", async () => {
  globalThis.fetch = async () =>
    new Response(
      JSON.stringify({
        error: {
          code: "SOURCE_RATE_LIMITED",
          message: "wait",
          action: "wait",
          retryable: true,
          retry_after_seconds: 2,
        },
      }),
      { status: 429, headers: { "Retry-After": "12" } },
    );
  await assert.rejects(api.analyze("https://youtu.be/test", "csrf", "ko"), (error: unknown) => {
    assert.ok(error instanceof ApiError);
    assert.equal(error.retryAfterSeconds, 12);
    assert.equal(error.retryable, true);
    assert.equal(error.status, 429);
    assert.ok(error.retryAt);
    return true;
  });
});
test("FE-05 empty 204 and empty successful mutation are accepted", async () => {
  globalThis.fetch = async () => new Response(null, { status: 204 });
  assert.equal(await api.deleteHistory("csrf", "id"), undefined);
  globalThis.fetch = async () => new Response("");
  assert.equal(await api.logout("csrf"), undefined);
});
test("FE-05 malformed JSON and unchecked critical successful bodies fail intentionally", async () => {
  globalThis.fetch = async () => new Response("{broken");
  await expectError(api.job("csrf", "id", { retries: 0 }), "INVALID_RESPONSE", 200);
  globalThis.fetch = async () =>
    new Response(JSON.stringify({ authenticated: true, bootstrapped: true, csrf_token: "" }));
  await expectError(api.session({ retries: 0 }), "INVALID_RESPONSE", 200);
});
test("FE-05 offline, bounded timeout, and deliberate cancellation remain distinct", async () => {
  globalThis.fetch = async () => {
    throw new TypeError("offline private diagnostic");
  };
  await expectError(api.job("csrf", "id", { retries: 0 }), "NETWORK_ERROR", null);
  globalThis.fetch = async (_input, init) =>
    new Promise((_resolve, reject) => {
      if (init?.signal?.aborted) reject(new DOMException("aborted", "AbortError"));
      init?.signal?.addEventListener(
        "abort",
        () => reject(new DOMException("aborted", "AbortError")),
        { once: true },
      );
    });
  await expectError(api.job("csrf", "id", { timeoutMs: 5, retries: 0 }), "TIMEOUT", null);
  const controller = new AbortController();
  controller.abort();
  await expectError(
    api.job("csrf", "id", { signal: controller.signal, retries: 0 }),
    "ABORTED",
    null,
  );
});
test("FE-06 unauthorized history deletion rejects rather than resolving a false success", async () => {
  globalThis.fetch = async () =>
    new Response(
      JSON.stringify({
        error: { code: "UNAUTHORIZED", message: "login", retryable: false, action: "login" },
      }),
      { status: 401 },
    );
  await expectError(api.deleteHistory("csrf", "id"), "UNAUTHORIZED", 401);
});
test("FE-06 failed cancel, retention, deletion, preferences, diagnostics and logout all reject", async () => {
  globalThis.fetch = async () =>
    new Response(
      JSON.stringify({
        error: { code: "STORAGE_FULL", message: "full", retryable: false, action: "clear" },
      }),
      { status: 409 },
    );
  for (const operation of [
    () => api.cancel("csrf", "id"),
    () => api.retention("csrf", "id", true),
    () => api.deleteFile("csrf", "id"),
    () => api.patchSettings("csrf", { language: "en" }),
    () => api.diagnostics("csrf"),
    () => api.logout("csrf"),
  ])
    await expectError(operation(), "STORAGE_FULL", 409);
});
test("FE-05 only safe reads retry, and retries remain bounded", async () => {
  let count = 0;
  globalThis.fetch = async () => {
    count += 1;
    return new Response("gateway", { status: 503 });
  };
  await expectError(api.job("csrf", "id"), "HTTP_503", 503);
  assert.equal(count, 2);
  count = 0;
  await expectError(api.cancel("csrf", "id"), "HTTP_503", 503);
  assert.equal(count, 1);
});
test("FE-05 response byte cap covers chunked bodies and early declared length", async () => {
  globalThis.fetch = async () =>
    new Response(
      new ReadableStream({
        start(controller) {
          controller.enqueue(new Uint8Array(2 * 1024 * 1024 + 1));
          controller.close();
        },
      }),
    );
  await expectError(api.job("csrf", "id", { retries: 0 }), "RESPONSE_TOO_LARGE", 200);
  globalThis.fetch = async () =>
    new Response("{}", { headers: { "Content-Length": "9999999999" } });
  await expectError(api.job("csrf", "id", { retries: 0 }), "RESPONSE_TOO_LARGE", 200);
});
test("FE-25 large native file HEAD does not buffer the artifact or reject its Content-Length", async () => {
  globalThis.fetch = async (_input, init) => {
    assert.equal(init?.method, "HEAD");
    return new Response(null, { headers: { "Content-Length": "9999999999" } });
  };
  assert.equal(await api.checkFile("csrf", "id"), undefined);
});

test("FE-25 empty HEAD failures map missing/expired artifacts to actionable recovery", async () => {
  globalThis.fetch = async () => new Response(null, { status: 410 });
  await expectError(api.checkFile("csrf", "id"), "FILE_EXPIRED", 410);
  globalThis.fetch = async () => new Response(null, { status: 404 });
  await expectError(api.checkFile("csrf", "id"), "FILE_MISSING", 404);
  globalThis.fetch = async () => new Response(null, { status: 401 });
  await expectError(api.checkFile("csrf", "id"), "HTTP_401", 401);
});
