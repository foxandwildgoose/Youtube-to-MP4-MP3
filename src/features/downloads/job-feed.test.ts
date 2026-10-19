import assert from "node:assert/strict";
import { test } from "node:test";
import { setTimeout as delay } from "node:timers/promises";
import { JobFeed, type FeedState } from "./job-feed.ts";
import { ApiError } from "./api.ts";
import { activeJobs, mergeJobs, type JobEntities } from "./job-store.ts";
import { fixtureJob } from "./test-fixtures.ts";
class FakeSource {
  listeners = new Map<string, ((event: MessageEvent) => void)[]>();
  closed = false;
  addEventListener(type: string, handler: (event: MessageEvent) => void) {
    this.listeners.set(type, [...(this.listeners.get(type) || []), handler]);
  }
  close() {
    this.closed = true;
  }
  emit(type: string, data?: unknown) {
    for (const listener of this.listeners.get(type) || []) {
      const event = new MessageEvent(type, { data: JSON.stringify(data) });
      listener(event);
    }
  }
}
test("FE-01/03 restored six-plus jobs share at most two streams and recurring fallback reaches completion", async () => {
  const sources: FakeSource[] = [];
  const states: FeedState[] = [];
  let polls = 0;
  let entities: JobEntities = new Map();
  const jobs = Array.from({ length: 8 }, (_, index) => fixtureJob(`job-${index}`, 1));
  const feed = new JobFeed({
    pollMs: 8,
    discover: async () => {
      polls += 1;
      return jobs.map((job) => ({
        ...job,
        revision: polls,
        status: polls >= 3 ? "succeeded" : "running",
      }));
    },
    accept: (snapshots) => {
      entities = mergeJobs(entities, snapshots);
      feed.sync(activeJobs(entities));
    },
    source: () => {
      const source = new FakeSource();
      sources.push(source);
      assert.ok(sources.filter((item) => !item.closed).length <= 2);
      return source;
    },
    state: (state) => states.push(state),
    error: (error) => {
      throw error;
    },
    expired: () => assert.fail("unexpected expiry"),
  });
  try {
    feed.start();
    await delay(2);
    assert.equal(sources.length, 2);
    assert.equal(states.includes("live"), false);
    sources[0].emit("open");
    assert.ok(states.includes("live"));
    sources[0].emit("error");
    sources[1].emit("error");
    await delay(35);
    assert.ok(polls >= 3);
    assert.equal(activeJobs(entities).length, 0);
    assert.ok(sources.every((source) => source.closed));
    assert.ok(sources.length <= 4); // Other queued jobs may use a free stream; concurrent streams stay bounded.
  } finally {
    feed.stop();
  }
});
test("FE-03 bye closes streams, revalidates revoked authentication, and no callbacks survive stop", async () => {
  const sources: FakeSource[] = [];
  let expired = 0;
  let accepts = 0;
  const feed = new JobFeed({
    pollMs: 5,
    discover: async () => [fixtureJob()],
    accept: (jobs) => {
      accepts += 1;
      feed.sync(jobs);
    },
    source: () => {
      const source = new FakeSource();
      sources.push(source);
      return source;
    },
    state: () => {},
    error: () => {},
    expired: () => {
      expired += 1;
    },
  });
  feed.start();
  await delay(2);
  sources[0].emit("bye", { authenticated: false });
  assert.equal(expired, 1);
  assert.equal(sources[0].closed, true);
  const count = accepts;
  sources[0].emit("snapshot", fixtureJob("one", 50, "succeeded"));
  await delay(15);
  assert.equal(accepts, count);
});
test("FE-01 offline recovery refreshes automatically and close/error fallback never duplicates subscriptions", async () => {
  const sources: FakeSource[] = [];
  let polls = 0;
  const states: FeedState[] = [];
  const feed = new JobFeed({
    pollMs: 100,
    discover: async () => {
      polls += 1;
      return [fixtureJob()];
    },
    accept: (jobs) => feed.sync(jobs),
    source: () => {
      const source = new FakeSource();
      sources.push(source);
      return source;
    },
    state: (state) => states.push(state),
    error: () => {},
    expired: () => {},
  });
  try {
    feed.start();
    await delay(2);
    feed.sync([fixtureJob()]);
    assert.equal(sources.length, 1);
    feed.setOnline(false);
    assert.equal(states.at(-1), "offline");
    assert.equal(sources[0].closed, true);
    feed.setOnline(true);
    await delay(2);
    assert.equal(polls, 2);
    assert.equal(sources.length, 2);
    sources[1].emit("bye", { error: "not-found" });
    assert.equal(sources[1].closed, true);
  } finally {
    feed.stop();
  }
});
test("FE-04 unauthorized recurring discovery expires the session and aborts polling", async () => {
  let polls = 0;
  let expired = 0;
  const feed = new JobFeed({
    pollMs: 5,
    discover: async () => {
      polls += 1;
      throw new ApiError({ code: "UNAUTHORIZED", status: 401 });
    },
    accept: () => assert.fail("no authenticated entities"),
    state: () => {},
    error: () => {},
    expired: () => {
      expired += 1;
    },
  });
  feed.start();
  await delay(20);
  assert.equal(expired, 1);
  assert.equal(polls, 1);
  feed.stop();
});

test("FE-03 late error from a replaced stream cannot close its new subscription", async () => {
  const sources: FakeSource[] = [];
  let now = 0;
  const feed = new JobFeed({
    now: () => now,
    pollMs: 1000,
    discover: async () => [fixtureJob()],
    accept: (jobs) => feed.sync(jobs),
    source: () => {
      const source = new FakeSource();
      sources.push(source);
      return source;
    },
    state: () => {},
    error: () => {},
    expired: () => {},
  });
  try {
    feed.start();
    await delay(2);
    sources[0].emit("error");
    now = 10001;
    feed.sync([fixtureJob()]);
    assert.equal(sources.length, 2);
    sources[0].emit("error");
    assert.equal(sources[1].closed, false);
    feed.sync([fixtureJob()]);
    assert.equal(sources.length, 2);
  } finally {
    feed.stop();
  }
});
