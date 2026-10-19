#!/usr/bin/env node
/** Real passwordless local UI, session renewal, worker and native-download checks.
 * No passwords, bootstrap calls, external server or live YouTube calls are used.
 * Start only the isolated seorap-passwordless-fixture Compose project first.
 * agent-browser drives interaction; Playwright observes the same CDP browser.
 */
import assert from "node:assert/strict";
import { spawn, execFile } from "node:child_process";
import { randomUUID } from "node:crypto";
import { createServer } from "node:net";
import { readFile, writeFile, mkdir } from "node:fs/promises";
import { join, resolve } from "node:path";
import { promisify } from "node:util";
import { chromium } from "playwright";
import AxeBuilder from "@axe-core/playwright";

const exec = promisify(execFile);
const root = resolve(import.meta.dirname, "..");
const base = new URL("http://127.0.0.1:18002");
const project = "seorap-passwordless-fixture";
const runId = randomUUID().slice(0, 8);
const output = resolve(
  process.env.SEORAP_PASSWORDLESS_OUTPUT || `/workspace/screenshots/passwordless-${runId}`,
);
assert(output.startsWith("/workspace/screenshots/"));
await mkdir(output, { recursive: true });
try {
  const previous = await readFile(join(output, "verification.json"), "utf8");
  const archived = JSON.parse(previous);
  await mkdir(join(output, "attempts"), { recursive: true });
  await writeFile(join(output, "attempts", `${archived.runId}.json`), previous);
} catch (error) {
  if (error.code !== "ENOENT") throw error;
}
await mkdir("/workspace/.cache/agent-browser", { recursive: true });
const env = { ...process.env, AGENT_BROWSER_SOCKET_DIR: "/workspace/.cache/agent-browser" };
const composeFiles = process.env.SEORAP_PASSWORDLESS_COMPOSE_FILES
  ? process.env.SEORAP_PASSWORDLESS_COMPOSE_FILES.split(",")
  : [
      "docker-compose.yml",
      ...(process.env.CODEX_PROXY_CERT ? ["docker-compose.cloud.yml"] : []),
      "docker-compose.fixture.yml",
      "docker-compose.override.yml",
      "docker-compose.passwordless-fixture.yml",
    ];
assert.equal(composeFiles[0], "docker-compose.yml");
assert.equal(composeFiles.at(-1), "docker-compose.passwordless-fixture.yml");
assert(composeFiles.includes("docker-compose.fixture.yml"));
assert(
  composeFiles.indexOf("docker-compose.override.yml") >
    composeFiles.indexOf("docker-compose.fixture.yml"),
  "Personal passwordless override must follow the protected fixture overlay",
);
assert(
  composeFiles.every((file) =>
    [
      "docker-compose.yml",
      "docker-compose.cloud.yml",
      "docker-compose.fixture.yml",
      "docker-compose.override.yml",
      "docker-compose.passwordless-fixture.yml",
    ].includes(file),
  ),
  "Use only the explicit isolated passwordless fixture Compose files",
);
const report = {
  runId,
  kind: "isolated-passwordless-ui-worker-synthetic-media",
  startedAt: new Date().toISOString(),
  baseURL: base.origin,
  liveYouTube: "skipped: no explicitly permitted LIVE_TEST_URL used",
  observerRepairHistory:
    "First observer rejected normal canceled reads/native download handoff; classification now requires successful current reads or completed exact-job native bytes. Input automation now clears the field and checks its exact value before analysis.",
  gates: [],
  screenshots: [],
  accessibility: [],
  responses: [],
  consoleErrors: [],
  pageErrors: [],
  failedRequests: [],
  outputs: [],
};
const pause = (ms) => new Promise((done) => setTimeout(done, ms));
let chrome,
  browser,
  context,
  page,
  port,
  session,
  activeGate = "",
  cookie = "",
  csrf = "";
const transfers = [],
  completed = new Set();
async function poll(work, condition, timeout = 45000) {
  const end = Date.now() + timeout;
  do {
    const value = await work();
    if (condition(value)) return value;
    await pause(150);
  } while (Date.now() < end);
  throw Error("Timed out waiting for actual passwordless fixture state");
}
async function gate(name, work) {
  activeGate = name;
  const started = Date.now();
  try {
    const facts = await work();
    report.gates.push({ name, status: "passed", durationMs: Date.now() - started, ...facts });
    console.log(JSON.stringify({ gate: name, status: "passed" }));
  } catch (error) {
    report.gates.push({ name, status: "failed", error: error.message });
    throw error;
  } finally {
    activeGate = "";
  }
}
async function agent(args, input) {
  return new Promise((done, reject) => {
    const child = spawn(
      "npm",
      [
        "exec",
        "--yes",
        "--cache",
        "/workspace/.cache/npm",
        "--package=agent-browser@0.39.1",
        "--",
        "agent-browser",
        "--session",
        session,
        "--pin-tab",
        "--cdp",
        String(port),
        "--json",
        ...args,
      ],
      { cwd: root, env, stdio: ["pipe", "pipe", "pipe"] },
    );
    let stdout = "",
      stderr = "";
    child.stdout.on("data", (chunk) => (stdout += chunk));
    child.stderr.on("data", (chunk) => (stderr += chunk));
    child.on("error", reject);
    child.on("exit", (code) => {
      if (code)
        return reject(Error(`agent-browser ${args[0]}: ${(stderr || stdout).slice(-2500)}`));
      try {
        done(JSON.parse(stdout));
      } catch {
        done(stdout);
      }
    });
    child.stdin.end(input);
  });
}
const batch = (commands) => agent(["batch", "--bail"], JSON.stringify(commands));
const button = (name) => ["find", "role", "button", "click", "--name", name, "--exact"];
const check = (source, message) => [
  "eval",
  `(() => {if (!(${source})) throw Error(${JSON.stringify(message)}); return true})()`,
];
const noLogin = () =>
  check(
    '!document.querySelector("#local-password") && !document.querySelector("input[type=password]") && ![...document.querySelectorAll("button")].some(b => /^(로그인|로그아웃|Log in|Log out)$/.test(b.textContent.trim())) && !!document.querySelector("#video-url")',
    "Passwordless app unexpectedly requires setup, login, or logout",
  );
async function screenshot(name) {
  const file = join(output, `${name}.png`);
  await agent(["screenshot", file, "--full"]);
  report.screenshots.push(file);
}
async function audit(name) {
  const result = await new AxeBuilder({ page })
    .withTags(["wcag2a", "wcag2aa", "wcag21aa"])
    .analyze();
  const violations = result.violations.map((value) => ({
    id: value.id,
    impact: value.impact,
    nodes: value.nodes.map((node) => node.target),
  }));
  report.accessibility.push({ name, violations });
  assert.equal(violations.length, 0, `Axe ${name}: ${JSON.stringify(violations)}`);
}
async function api(path, options = {}) {
  const response = await fetch(new URL(`/api/v1${path}`, base), {
    ...options,
    headers: {
      Cookie: cookie,
      Origin: base.origin,
      "X-CSRF-Token": csrf,
      "X-Requested-With": "seorap",
      "Content-Type": "application/json",
      ...options.headers,
    },
    signal: AbortSignal.timeout(15000),
  });
  assert(
    response.ok,
    `Fixture API ${path}: ${response.status} ${(await response.clone().text()).slice(0, 600)}`,
  );
  return response.status === 204 ? null : response.json();
}
async function credentials() {
  const cookies = await context.cookies(base.origin);
  cookie = cookies.map((item) => `${item.name}=${item.value}`).join("; ");
  const data = await api("/auth/session");
  assert.equal(data.authenticated, true);
  assert.equal(data.password_required, false);
  csrf = data.csrf_token;
  const ownCookie = cookies.find((item) => item.name === "seorap_session");
  assert(ownCookie && ownCookie.httpOnly && ownCookie.sameSite === "Lax");
  return { authenticated: true, passwordRequired: false, httpOnly: true, sameSite: "Lax" };
}
async function fixtureDb(script) {
  const { stdout } = await exec(
    "docker",
    [
      "compose",
      "-p",
      project,
      ...composeFiles.flatMap((file) => ["-f", file]),
      "exec",
      "-T",
      "app",
      "python",
      "-c",
      "from app.config import load_settings\nfrom app.db import connect\ns=load_settings(); assert s.demo_data and s.allow_test_hooks and not s.require_password\nc=connect(s)\n" +
        script,
    ],
    { cwd: root, env },
  );
  return stdout ? JSON.parse(stdout) : null;
}
async function launch(label) {
  session = `passwordless-${runId}-${label}`;
  const server = createServer();
  await new Promise((done) => server.listen(0, "127.0.0.1", done));
  port = server.address().port;
  await new Promise((done) => server.close(done));
  chrome = spawn(
    process.env.CHROMIUM_PATH || "/usr/bin/chromium",
    [
      "--headless",
      "--no-sandbox",
      "--disable-dev-shm-usage",
      `--remote-debugging-port=${port}`,
      `--user-data-dir=/workspace/.cache/browser-${session}`,
      "about:blank",
    ],
    { stdio: "ignore" },
  );
  await poll(
    async () => {
      try {
        return (await fetch(`http://127.0.0.1:${port}/json/version`)).ok;
      } catch {
        return false;
      }
    },
    Boolean,
    15000,
  );
  browser = await chromium.connectOverCDP(`http://127.0.0.1:${port}`);
  context = browser.contexts()[0];
  const control = await browser.newBrowserCDPSession();
  control.on("Browser.downloadWillBegin", (value) => transfers.push(value));
  control.on("Browser.downloadProgress", (value) => {
    if (value.state === "completed") completed.add(value.guid);
  });
  await control.send("Browser.setDownloadBehavior", {
    behavior: "allowAndName",
    downloadPath: output,
    eventsEnabled: true,
  });
  function observe(value) {
    value.on("pageerror", (error) =>
      report.pageErrors.push({ gate: activeGate, error: error.message }),
    );
    value.on("console", (message) => {
      if (message.type() === "error")
        report.consoleErrors.push({
          gate: activeGate,
          message: message.text(),
          location: message.location(),
        });
    });
    value.on("requestfailed", (request) =>
      report.failedRequests.push({
        gate: activeGate,
        at: Date.now(),
        url: request.url(),
        method: request.method(),
        error: request.failure()?.errorText,
      }),
    );
    value.on("response", (response) => {
      if (response.url().startsWith(base.origin + "/api/"))
        report.responses.push({
          gate: activeGate,
          at: Date.now(),
          url: response.url(),
          method: response.request().method(),
          status: response.status(),
        });
    });
  }
  context.pages().forEach(observe);
  context.on("page", observe);
}
async function closeBrowser() {
  try {
    if (browser) await browser.close();
  } catch {
    /* process cleanup follows */
  }
  if (chrome) chrome.kill("SIGTERM");
  browser = null;
  chrome = null;
}
async function analyze(kind) {
  const existing = await page.locator("#video-url").inputValue();
  await batch([
    ...(existing
      ? [button("지우기"), ["wait", "--fn", 'document.querySelector("#video-url")?.value === ""']]
      : []),
    ["fill", "#video-url", "https://www.youtube.com/watch?v=fixH264aacA"],
    check(
      'document.querySelector("#video-url")?.value === "https://www.youtube.com/watch?v=fixH264aacA"',
      "Browser input automation did not enter the exact fixture URL",
    ),
    button("링크 분석"),
    ["wait", "--fn", '!!document.querySelector(".analysis-result")'],
    [
      "find",
      "role",
      "tab",
      "click",
      "--name",
      kind === "mp4" ? "MP4 영상" : "MP3 오디오",
      "--exact",
    ],
    ["wait", "--fn", `!!document.querySelector('#quality-${kind}')?.value`],
  ]);
}
async function createAndDownload(kind, recovery) {
  const before = (await api("/jobs?limit=100")).jobs;
  const ids = new Set(before.map((job) => job.id));
  const selected = await page.locator(`#quality-${kind}`).inputValue();
  const responsesBefore = report.responses.length;
  if (recovery === "expiry")
    await fixtureDb(
      "c.execute(\"UPDATE sessions SET expires_at='2000-01-01T00:00:00+00:00'\");c.close()",
    );
  await batch([
    ...(recovery === "lost-cookie" ? [["cookies", "clear"]] : []),
    button(kind === "mp4" ? "MP4 만들기" : "MP3 만들기"),
    ["wait", "--fn", `document.querySelectorAll('article[data-job-id]').length > ${before.length}`],
    noLogin(),
    check(
      `document.querySelector('#quality-${kind}')?.value === ${JSON.stringify(selected)} && document.querySelector('#video-url')?.value.includes('fixH264aacA') && !!document.querySelector('.analysis-result')`,
      "Session recovery discarded the chosen source or output",
    ),
  ]);
  await credentials();
  const created = (await api("/jobs?limit=100")).jobs.filter((job) => !ids.has(job.id));
  assert.equal(created.length, 1, "One user click must create exactly one job");
  const job = await poll(
    () => api(`/jobs/${created[0].id}`),
    (value) => !["queued", "running"].includes(value.status),
  );
  assert.equal(job.status, "succeeded", JSON.stringify(job.error));
  assert.equal(job.output.kind, kind, "Delivered output differs from the user selection");
  if (kind === "mp3") assert.equal(job.output.bitrate_kbps, 320);
  await agent([
    "wait",
    "--fn",
    `document.querySelector('article[data-job-id="${job.id}"]')?.textContent.includes('받을 수 있음')`,
  ]);
  const recoveryResponses = report.responses.slice(responsesBefore);
  const rejected = recoveryResponses.filter(
    (response) =>
      response.method === "POST" && response.url.endsWith("/jobs") && response.status === 401,
  );
  const accepted = recoveryResponses.filter(
    (response) =>
      response.method === "POST" && response.url.endsWith("/jobs") && response.status === 202,
  );
  const renewed = recoveryResponses.filter(
    (response) => response.url.endsWith("/auth/session") && response.status === 200,
  );
  assert.equal(rejected.length, 1, "Expiry/lost cookie must exercise a real job API 401");
  assert.equal(accepted.length, 1, "The guarded job request must retry once only");
  assert(renewed.length >= 1 && renewed.length <= 3, "Session refresh must be bounded");
  assert.equal((await api("/settings")).mp3_bitrate, 320, "Recovery lost saved preferences");
  const count = transfers.length;
  await batch([
    ["click", `article[data-job-id="${job.id}"] .job-actions > button.primary`],
    noLogin(),
  ]);
  const transfer = await poll(async () => transfers[count], Boolean, 20000);
  await poll(async () => completed.has(transfer.guid), Boolean, 20000);
  assert.equal(
    new URL(transfer.url).pathname,
    `/api/v1/jobs/${job.id}/file`,
    "Native download came from a different job",
  );
  const bytes = await readFile(join(output, transfer.guid));
  assert.equal(bytes.length, job.artifact.bytes);
  assert(bytes.length > 100);
  const file = join(output, `native-${job.id}.${kind}`);
  await writeFile(file, bytes);
  const { stdout } = await exec(process.env.FFPROBE_PATH || "ffprobe", [
    "-v",
    "error",
    "-show_format",
    "-show_streams",
    "-of",
    "json",
    file,
  ]);
  const probed = JSON.parse(stdout);
  assert(Number(probed.format.duration) > 0);
  if (kind === "mp4") {
    assert(probed.streams.some((stream) => stream.codec_name === "h264"));
    assert(probed.streams.some((stream) => stream.codec_name === "aac"));
  } else {
    assert(probed.streams.every((stream) => stream.codec_type === "audio"));
    assert(
      probed.streams.some(
        (stream) =>
          stream.codec_name === "mp3" && Math.abs(Number(stream.bit_rate) - 320000) <= 1000,
      ),
    );
  }
  const facts = {
    jobId: job.id,
    recovery,
    rejectedJobRequests: rejected.length,
    acceptedJobRequests: accepted.length,
    sessionRefreshResponses: renewed.length,
    requestedKind: kind,
    actualKind: job.output.kind,
    bytes: bytes.length,
    nativePath: file,
    transferPath: new URL(transfer.url).pathname,
    streams: probed.streams.map((stream) => ({
      codec: stream.codec_name,
      type: stream.codec_type,
      bitrate: stream.bit_rate,
    })),
  };
  report.outputs.push(facts);
  await screenshot(`${kind}-ready-passwordless`);
  await audit(`${kind}-ready-passwordless`);
  return facts;
}
try {
  await gate("fresh-passwordless-first-open-desktop", async () => {
    const health = await fetch(new URL("/healthz", base));
    assert(health.ok);
    assert.equal(
      await fixtureDb(
        "import json;print(json.dumps(c.execute('SELECT count(*) FROM operator').fetchone()[0]));c.close()",
      ),
      0,
      "Fixture must have no bootstrapped password",
    );
    await launch("desktop");
    await batch([
      ["open", base.href],
      ["set", "viewport", "1280", "900"],
      ["wait", "--fn", '!!document.querySelector("#video-url")'],
      noLogin(),
    ]);
    page = context.pages().find((value) => value.url().startsWith(base.origin));
    assert(page);
    const facts = await credentials();
    assert.equal((await api("/settings")).capabilities.demo_data, true);
    await screenshot("first-open-desktop");
    await audit("first-open-desktop");
    return { ...facts, operatorRows: 0, bootstrapUsed: false, loginUsed: false };
  });
  await gate("saved-preferences-and-reload-without-login", async () => {
    await batch([
      button("설정"),
      ["select", ".settings-fields label:nth-child(3) select", "320"],
      [
        "wait",
        "--fn",
        'document.querySelector(".settings-fields")?.getAttribute("aria-busy") === "false"',
      ],
      ["press", "Escape"],
      ["reload"],
      ["wait", "--fn", '!!document.querySelector("#video-url")'],
      noLogin(),
    ]);
    await credentials();
    assert.equal((await api("/settings")).mp3_bitrate, 320);
    await screenshot("reload-desktop");
    return { savedBitrate: 320, reloadRequiresPassword: false };
  });
  await gate("lost-cookie-real-401-silent-renewal-mp4-native-download", async () => {
    await analyze("mp4");
    return createAndDownload("mp4", "lost-cookie");
  });
  await gate("expired-session-real-401-silent-renewal-mp3-native-download", async () => {
    await analyze("mp3");
    return createAndDownload("mp3", "expiry");
  });
  await gate("mobile-no-login-no-overflow-accessibility", async () => {
    await batch([
      ["set", "viewport", "390", "844"],
      noLogin(),
      check("document.documentElement.scrollWidth <= innerWidth + 1", "Mobile content overflows"),
    ]);
    await screenshot("mobile-ready");
    await audit("mobile-ready");
    await batch([button("설정"), ["wait", "--fn", '!!document.querySelector("[role=dialog]")']]);
    await screenshot("mobile-settings");
    await audit("mobile-settings");
    await batch([["press", "Escape"]]);
    return { viewport: "390x844", horizontalOverflow: false };
  });
  await gate("new-browser-context-opens-without-password", async () => {
    await closeBrowser();
    await launch("fresh");
    assert.equal((await context.cookies(base.origin)).length, 0);
    await batch([
      ["open", base.href],
      ["set", "viewport", "390", "844"],
      ["wait", "--fn", '!!document.querySelector("#video-url")'],
      noLogin(),
    ]);
    page = context.pages().find((value) => value.url().startsWith(base.origin));
    const facts = await credentials();
    assert.equal((await api("/settings")).mp3_bitrate, 320);
    await screenshot("new-context-mobile");
    await audit("new-context-mobile");
    return { ...facts, previouslyEmptyCookieJar: true, savedPreferencesRetained: true };
  });
  await gate("strict-runtime-console-and-no-auth-interaction", async () => {
    const recoveryGates = new Set([
      "lost-cookie-real-401-silent-renewal-mp4-native-download",
      "expired-session-real-401-silent-renewal-mp3-native-download",
    ]);
    report.expectedRecoveryErrors = report.consoleErrors.filter(
      (error) =>
        recoveryGates.has(error.gate) &&
        /^Failed to load resource: the server responded with a status of 401/.test(error.message) &&
        error.location.url === base.origin + "/api/v1/jobs",
    );
    report.externalGrok = report.failedRequests.filter((error) =>
      error.url.startsWith("https://grok.com/"),
    );
    report.unexpectedConsoleErrors = report.consoleErrors.filter(
      (error) =>
        !report.expectedRecoveryErrors.includes(error) &&
        !error.location.url.startsWith("https://grok.com/"),
    );
    // AbortController cancels stale read requests during session replacement,
    // and Chromium reports native download handoff as an aborted page request.
    // Keep those observed cancellations separate; actual native transfer bytes
    // and completion were verified above. Other transport failures still fail.
    report.expectedCancellations = report.failedRequests.filter((error) => {
      if (!["GET", "HEAD"].includes(error.method) || error.error !== "net::ERR_ABORTED")
        return false;
      const url = new URL(error.url);
      if (url.origin !== base.origin) return false;
      const file = url.pathname.match(/^\/api\/v1\/jobs\/([a-f0-9]+)\/file$/);
      if (file)
        return (
          report.outputs.some((value) => value.jobId === file[1] && value.bytes > 100) &&
          report.responses.some(
            (value) => value.url === error.url && value.status === 200 && value.method === "HEAD",
          )
        );
      if (error.method !== "GET") return false;
      const events = url.pathname.match(/^\/api\/v1\/jobs\/([a-f0-9]+)\/events$/);
      if (events)
        return (
          report.outputs.some((value) => value.jobId === events[1]) &&
          report.responses.some((value) => value.url === error.url && value.status === 200)
        );
      if (!/^\/api\/v1\/(auth\/session|jobs|settings|readiness)$/.test(url.pathname)) return false;
      return report.responses.some(
        (value) =>
          value.method === "GET" &&
          value.status === 200 &&
          value.at >= error.at &&
          new URL(value.url).pathname === url.pathname,
      );
    });
    report.unexpectedFailedRequests = report.failedRequests.filter(
      (error) =>
        !error.url.startsWith("https://grok.com/") && !report.expectedCancellations.includes(error),
    );
    assert.deepEqual(report.unexpectedConsoleErrors, []);
    assert.deepEqual(report.unexpectedFailedRequests, []);
    assert.deepEqual(report.pageErrors, []);
    assert(
      !report.responses.some((response) => /\/auth\/(login|bootstrap|logout)$/.test(response.url)),
    );
    return {
      unexpectedConsoleErrors: 0,
      pageErrors: 0,
      bootstrapLoginLogoutRequests: 0,
      externalGrokRequestsBlocked: report.externalGrok.length,
    };
  });
  report.ok = true;
} catch (error) {
  report.ok = false;
  report.error = String(error.stack || error);
  console.error(report.error);
  if (page)
    try {
      await screenshot("failure");
    } catch {
      /* diagnostic only */
    }
  process.exitCode = 1;
} finally {
  await closeBrowser();
  report.finishedAt = new Date().toISOString();
  await writeFile(join(output, "verification.json"), JSON.stringify(report, null, 2) + "\n");
  console.log(JSON.stringify({ ok: report.ok, report: join(output, "verification.json") }));
}
