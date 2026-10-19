import assert from "node:assert/strict";
import { test } from "node:test";
import { api, ApiError } from "./api.ts";
import { isJob, type Job } from "./contracts.ts";
import { activeJobs, mergeJobs, orderedJobs, type JobEntities } from "./job-store.ts";
import {
  AnalysisGeneration,
  readIntent,
  sameRequest,
  writeIntent,
  type SubmissionIntent,
} from "./submission.ts";
import { localPreferences, PreferenceWriter } from "./preferences.ts";
import { fixtureJob } from "./test-fixtures.ts";
function storage() {
  const data = new Map<string, string>();
  return {
    getItem: (key: string) => data.get(key) ?? null,
    setItem: (key: string, value: string) => {
      data.set(key, value);
    },
    removeItem: (key: string) => {
      data.delete(key);
    },
  };
}
test("FE-02 reversed list, feed, and mutation responses never decrease revisions or lose new jobs", () => {
  let entities: JobEntities = new Map();
  entities = mergeJobs(entities, [fixtureJob("old", 1)]);
  entities = mergeJobs(entities, [fixtureJob("new", 1), fixtureJob("old", 4, "succeeded")]);
  entities = mergeJobs(entities, [fixtureJob("old", 2)]);
  entities = mergeJobs(entities, [fixtureJob("old", 3, "cancelled")]);
  assert.equal(entities.get("old")?.revision, 4);
  assert.equal(entities.get("old")?.status, "succeeded");
  assert.ok(entities.has("new"));
  const before = orderedJobs(entities).map((job) => job.id);
  entities = mergeJobs(entities, [fixtureJob("new", 8)]);
  assert.deepEqual(
    orderedJobs(entities).map((job) => job.id),
    before,
  );
  assert.deepEqual(
    activeJobs(entities).map((job) => job.id),
    ["new"],
  );
});
test("FE-02 equal revision cannot replace canonical execution facts", () => {
  const original = mergeJobs(new Map(), [fixtureJob("same", 5, "succeeded")]);
  assert.equal(mergeJobs(original, [fixtureJob("same", 5)]), original);
});
test("FE-05 critical runtime shape checks reject poisoned revision and invalid status", () => {
  assert.equal(isJob(fixtureJob()), true);
  assert.equal(isJob({ ...fixtureJob(), revision: -1 }), false);
  assert.equal(isJob({ ...fixtureJob(), status: "almost-success" }), false);
  assert.equal(isJob({ ...fixtureJob(), output: null }), false);
});
test("FE-07 delayed old analysis cannot commit after editing or superseding input", () => {
  const generations = new AnalysisGeneration();
  const first = generations.begin();
  generations.invalidate();
  assert.equal(first.signal.aborted, true);
  assert.equal(first.current(), false);
  const second = generations.begin();
  const third = generations.begin();
  assert.equal(second.current(), false);
  assert.equal(third.current(), true);
});
test("FE-08 persistent exact intent survives response loss and replays one accepted job", async () => {
  const originalFetch = globalThis.fetch;
  const local = storage();
  const intent: SubmissionIntent = {
    key: "one-logical-request",
    body: {
      analysis_id: "analysis",
      choice_id: "choice",
      keep_on_server: false,
      conversion_consent: false,
    },
    parentId: null,
    videoId: "video",
    title: "source",
    createdAt: Date.now(),
  };
  writeIntent(local, intent);
  const server = new Map<string, Job>();
  let count = 0;
  globalThis.fetch = async (_input, init) => {
    const key = new Headers(init?.headers).get("Idempotency-Key")!;
    assert.deepEqual(JSON.parse(String(init?.body)), intent.body);
    if (!server.has(key)) server.set(key, fixtureJob(`job-${server.size + 1}`, 1, "queued"));
    count += 1;
    if (count === 1) throw new TypeError("acknowledgment dropped after commit");
    return new Response(JSON.stringify(server.get(key)), { status: 202 });
  };
  try {
    await assert.rejects(
      api.createJob("csrf", "ko", intent.key, intent.body),
      (error: unknown) => error instanceof ApiError && error.uncertain,
    );
    const restored = readIntent(local)!;
    assert.equal(sameRequest(restored, intent.body, null), true);
    assert.equal(sameRequest(restored, { ...intent.body, choice_id: "changed" }, null), false);
    const job = await api.createJob("csrf", "ko", restored.key, restored.body);
    assert.equal(job.id, "job-1");
    assert.equal(server.size, 1);
    writeIntent(local, null);
    assert.equal(readIntent(local), null);
    await api.createJob("csrf", "ko", "intentional-new-request", intent.body);
    assert.equal(server.size, 2);
  } finally {
    globalThis.fetch = originalFetch;
  }
});
test("FE-14 blocked or corrupted browser storage preserves safe initial preferences", () => {
  assert.deepEqual(
    localPreferences({
      getItem: () => {
        throw new Error("denied");
      },
    }),
    { language: "ko", theme: "system", mp3_bitrate: 192 },
  );
  const local = storage();
  local.setItem("seorap-lang", "en");
  local.setItem("seorap-theme", "dark");
  local.setItem("seorap-mp3-bitrate", "320");
  assert.deepEqual(localPreferences(local), { language: "en", theme: "dark", mp3_bitrate: 320 });
  assert.equal(
    readIntent({ getItem: () => "{broken", setItem: () => {}, removeItem: () => {} }),
    null,
  );
});
test("FE-14 rapid preference writes serialize, and only the latest save hydrates state", async () => {
  const writer = new PreferenceWriter();
  const writes: string[] = [];
  const accepted: string[] = [];
  let release!: (value: string) => void;
  const first = writer.save(
    () => {
      writes.push("first");
      return new Promise<string>((resolve) => {
        release = resolve;
      });
    },
    (value) => accepted.push(value),
  );
  const second = writer.save(
    async () => {
      writes.push("second");
      return "second";
    },
    (value) => accepted.push(value),
  );
  await Promise.resolve();
  await Promise.resolve();
  assert.deepEqual(writes, ["first"]);
  release("first");
  await Promise.all([first, second]);
  assert.deepEqual(writes, ["first", "second"]);
  assert.deepEqual(accepted, ["second"]);
});

test("FE-04 old authenticated requests cannot populate caches after logout or a new session", async () => {
  const { SessionScope } = await import("./session.ts");
  const scope = new SessionScope();
  let resolve!: (value: string) => void;
  let signal!: AbortSignal;
  const stale = scope.run((ownedSignal) => {
    signal = ownedSignal;
    return new Promise<string>((done) => {
      resolve = done;
    });
  });
  scope.reset();
  assert.equal(signal.aborted, true);
  resolve("old private session data");
  await assert.rejects(
    stale,
    (error: unknown) => error instanceof ApiError && error.code === "ABORTED",
  );
  assert.equal(await scope.run(async () => "new session"), "new session");
});
