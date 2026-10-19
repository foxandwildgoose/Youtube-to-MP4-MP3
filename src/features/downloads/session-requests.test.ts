import assert from "node:assert/strict";
import { test } from "node:test";
import { api, ApiError } from "./api.ts";
import type { Session } from "./contracts.ts";
import { SessionScope } from "./session.ts";
import { SessionRequests } from "./session-requests.ts";
import { fixtureJob } from "./test-fixtures.ts";

const session = (token = "old", passwordRequired = false): Session => ({
  authenticated: true,
  bootstrapped: true,
  csrf_token: token,
  expires_at: "2099-01-01T00:00:00Z",
  language: "ko",
  theme: "system",
  password_required: passwordRequired,
  bootstrap_allowed: false,
  bootstrap_method: null,
});
const unauthorized = () => new ApiError({ status: 401, code: "UNAUTHORIZED" });
const isAborted = (error: unknown) => error instanceof ApiError && error.code === "ABORTED";
function deferred<T>() {
  let resolve!: (value: T) => void;
  const promise = new Promise<T>((done) => {
    resolve = done;
  });
  return { promise, resolve };
}
function harness(
  options: { initial?: Session; refresh?: (signal: AbortSignal) => Promise<Session> } = {},
) {
  let current: Session | null = options.initial ?? session();
  let refreshCount = 0;
  const accepted: Session[] = [];
  const expired: { problem: ApiError; session: Session }[] = [];
  const failures: ApiError[] = [];
  const scope = new SessionScope();
  const requests = new SessionRequests({
    scope,
    current: () => current,
    refresh: async (signal) => {
      refreshCount += 1;
      return options.refresh ? options.refresh(signal) : session("fresh");
    },
    accept: (next) => {
      current = next;
      accepted.push(next);
    },
    expired: (problem, next) => expired.push({ problem, session: next }),
    refreshError: (problem) => failures.push(problem),
  });
  return {
    requests,
    scope,
    accepted,
    expired,
    failures,
    refreshCount: () => refreshCount,
    clear: () => {
      current = null;
      scope.reset();
    },
  };
}

test("passwordless cookie loss retries a rejected create with the same intent key and body", async () => {
  const originalFetch = globalThis.fetch;
  const requests = harness({ refresh: (signal) => api.session({ signal, retries: 0 }) });
  const body = {
    analysis_id: "analysis",
    choice_id: "choice",
    keep_on_server: false,
    conversion_consent: false,
  };
  const submitted: { token: string | null; key: string | null; body: unknown }[] = [];
  let committed = 0;
  globalThis.fetch = async (input, init) => {
    if (String(input) === "/api/v1/auth/session") return Response.json(session("fresh"));
    const headers = new Headers(init?.headers);
    submitted.push({
      token: headers.get("X-CSRF-Token"),
      key: headers.get("Idempotency-Key"),
      body: JSON.parse(String(init?.body)),
    });
    if (submitted.length === 1)
      return Response.json({ error: { code: "UNAUTHORIZED" } }, { status: 401 });
    committed += 1;
    return Response.json(fixtureJob("one-job"), { status: 202 });
  };
  try {
    const job = await requests.requests.run((token, options) =>
      api.createJob(token, "ko", "one-intent", body, options),
    );
    assert.equal(job.id, "one-job");
    assert.equal(committed, 1);
    assert.equal(requests.refreshCount(), 1);
    assert.deepEqual(submitted, [
      { token: "old", key: "one-intent", body },
      { token: "fresh", key: "one-intent", body },
    ]);
    assert.equal(requests.expired.length, 0);
  } finally {
    globalThis.fetch = originalFetch;
  }
});

test("passwordless stale CSRF token renews once and retries with the new token", async () => {
  const requests = harness();
  const tokens: string[] = [];
  const result = await requests.requests.run(async (token) => {
    tokens.push(token);
    if (token === "old") throw new ApiError({ status: 403, code: "CSRF_FAILED" });
    return "saved";
  });
  assert.equal(result, "saved");
  assert.deepEqual(tokens, ["old", "fresh"]);
  assert.equal(requests.refreshCount(), 1);
});

test("concurrent 401s and scheduled renewal share one session request", async () => {
  const fresh = deferred<Session>();
  const requests = harness({ refresh: () => fresh.promise });
  let failures = 0;
  const rejected = deferred<void>();
  const operation = async (token: string) => {
    if (token === "old") {
      failures += 1;
      if (failures === 2) rejected.resolve();
      throw unauthorized();
    }
    return token;
  };
  const first = requests.requests.run(operation);
  const second = requests.requests.run(operation);
  await rejected.promise;
  const scheduled = requests.requests.renew(session());
  fresh.resolve(session("fresh"));
  assert.deepEqual(await Promise.all([first, second, scheduled.then(() => "fresh")]), [
    "fresh",
    "fresh",
    "fresh",
  ]);
  assert.equal(requests.refreshCount(), 1);
});

test("a delayed old-session rejection reuses an already renewed session", async () => {
  const late = deferred<void>();
  const requests = harness();
  const tokens: string[] = [];
  const delayed = requests.requests.run(async (token) => {
    tokens.push(token);
    if (token === "old") {
      await late.promise;
      throw unauthorized();
    }
    return token;
  });
  await requests.requests.renew(session());
  late.resolve();
  assert.equal(await delayed, "fresh");
  assert.deepEqual(tokens, ["old", "fresh"]);
  assert.equal(requests.refreshCount(), 1);
});

test("repeated unauthorized rejection is bounded to one renewal and one replay", async () => {
  const requests = harness();
  let calls = 0;
  await assert.rejects(
    requests.requests.run(async () => {
      calls += 1;
      throw unauthorized();
    }),
    (error: unknown) => error instanceof ApiError && error.status === 401,
  );
  assert.equal(calls, 2);
  assert.equal(requests.refreshCount(), 1);
  assert.equal(requests.expired.length, 1);
  assert.equal(requests.expired[0].session.password_required, false);
});

test("protected session expiry still requires explicit login without replay or renewal", async () => {
  const requests = harness({ initial: session("protected", true) });
  let calls = 0;
  await assert.rejects(
    requests.requests.run(async () => {
      calls += 1;
      throw unauthorized();
    }),
  );
  assert.equal(calls, 1);
  assert.equal(requests.refreshCount(), 0);
  assert.equal(requests.expired[0].session.password_required, true);
});

test("protected CSRF renewal does not automatically replay the rejected operation", async () => {
  const requests = harness({
    initial: session("protected", true),
    refresh: async () => session("protected-fresh", true),
  });
  let calls = 0;
  await assert.rejects(
    requests.requests.run(async () => {
      calls += 1;
      throw new ApiError({ status: 403, code: "CSRF_FAILED" });
    }),
  );
  assert.equal(calls, 1);
  assert.equal(requests.refreshCount(), 1);
  assert.equal(requests.accepted.length, 1);
  assert.equal(requests.expired.length, 0);
});

test("ambiguous network, timeout and server failures never replay a mutation", async () => {
  for (const failure of [
    new ApiError({ code: "NETWORK_ERROR", uncertain: true }),
    new ApiError({ code: "TIMEOUT", uncertain: true }),
    new ApiError({ status: 503, code: "UNAVAILABLE", uncertain: true }),
  ]) {
    const requests = harness();
    let calls = 0;
    await assert.rejects(
      requests.requests.run(async () => {
        calls += 1;
        throw failure;
      }),
    );
    assert.equal(calls, 1);
    assert.equal(requests.refreshCount(), 0);
  }
});

test("cancelling one caller does not cancel another caller's shared renewal", async () => {
  const fresh = deferred<Session>();
  const requests = harness({ refresh: () => fresh.promise });
  const caller = new AbortController();
  const ready = deferred<void>();
  let firstCalls = 0;
  const first = requests.requests.run(async () => {
    firstCalls += 1;
    throw unauthorized();
  }, caller.signal);
  const firstRejection = assert.rejects(first, isAborted);
  const second = requests.requests.run(async (token) => {
    if (token === "old") {
      ready.resolve();
      throw unauthorized();
    }
    return "other caller completed";
  });
  await ready.promise;
  caller.abort();
  fresh.resolve(session("fresh"));
  await firstRejection;
  assert.equal(await second, "other caller completed");
  assert.equal(firstCalls, 1);
  assert.equal(requests.refreshCount(), 1);
});

test("an already cancelled caller never sends an action or renews its session", async () => {
  const requests = harness();
  const caller = new AbortController();
  caller.abort();
  let calls = 0;
  await assert.rejects(
    requests.requests.run(async () => {
      calls += 1;
    }, caller.signal),
    isAborted,
  );
  assert.equal(calls, 0);
  assert.equal(requests.refreshCount(), 0);
});

test("logout aborts a late renewal even when its network response ignores abort", async () => {
  const fresh = deferred<Session>();
  const ready = deferred<void>();
  const requests = harness({
    refresh: () => {
      ready.resolve();
      return fresh.promise;
    },
  });
  let calls = 0;
  const pending = requests.requests.run(async () => {
    calls += 1;
    throw unauthorized();
  });
  const rejected = assert.rejects(pending, isAborted);
  await ready.promise;
  requests.clear();
  fresh.resolve(session("late-private-session"));
  await rejected;
  assert.equal(calls, 1);
  assert.equal(requests.accepted.length, 0);
});

test("logout also discards a replay response that ignores abort", async () => {
  const replay = deferred<string>();
  const ready = deferred<void>();
  const requests = harness();
  const pending = requests.requests.run(async (token) => {
    if (token === "old") throw unauthorized();
    ready.resolve();
    return replay.promise;
  });
  const rejected = assert.rejects(pending, isAborted);
  await ready.promise;
  requests.clear();
  replay.resolve("old private response");
  await rejected;
});

test("changing the server to protected mode does not silently replay or bypass its login", async () => {
  const protectedSession: Session = {
    authenticated: false,
    bootstrapped: true,
    password_required: true,
    bootstrap_allowed: false,
    bootstrap_method: null,
  };
  const requests = harness({ refresh: async () => protectedSession });
  let calls = 0;
  await assert.rejects(
    requests.requests.run(async () => {
      calls += 1;
      throw unauthorized();
    }),
  );
  assert.equal(calls, 1);
  assert.equal(requests.expired[0].session.password_required, true);
});

test("a failed session renewal reports connection failure without replaying or inventing login", async () => {
  const requests = harness({
    refresh: async () => {
      throw new ApiError({ code: "NETWORK_ERROR" });
    },
  });
  let calls = 0;
  await assert.rejects(
    requests.requests.run(async () => {
      calls += 1;
      throw unauthorized();
    }),
    (error: unknown) => error instanceof ApiError && error.code === "NETWORK_ERROR",
  );
  assert.equal(calls, 1);
  assert.equal(requests.refreshCount(), 1);
  assert.equal(requests.expired.length, 0);
  assert.equal(requests.failures[0].code, "NETWORK_ERROR");
});
