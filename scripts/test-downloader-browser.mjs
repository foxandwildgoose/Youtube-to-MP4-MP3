#!/usr/bin/env node
/** Real authenticated UI + fixture API/worker/media journey. Never contacts YouTube.
 * Start the isolated fixture Compose stack and CLI-bootstrap it first. Run:
 * SEORAP_BROWSER_PASSWORD_FILE=/tmp/seorap-fixture-password npm run test:browser
 * agent-browser drives interaction; Playwright only observes/audits the same CDP browser.
 */
import assert from "node:assert/strict";
import { spawn, execFile } from "node:child_process";
import { chmod, mkdir, readFile, rename, writeFile } from "node:fs/promises";
import { join, resolve } from "node:path";
import { createServer } from "node:net";
import { promisify } from "node:util";
import { randomUUID } from "node:crypto";
import { chromium } from "playwright";
import AxeBuilder from "@axe-core/playwright";

const exec = promisify(execFile);
const root = resolve(import.meta.dirname, "..");
const base = new URL(process.env.SEORAP_BROWSER_URL || "http://127.0.0.1:18000");
assert(
  ["127.0.0.1", "localhost", "[::1]"].includes(base.hostname),
  "Fixture browser tests require loopback",
);
const project = process.env.SEORAP_COMPOSE_PROJECT || "seorap-packaging";
const bridgeMode = process.env.SEORAP_BROWSER_MODE === "bridge";
const stressMode = process.env.SEORAP_BROWSER_MODE === "stress";
const stressGates = new Set([
  "fixture-runtime",
  "actual-result-seven-job-queue-responsive-dialogs-and-playlist",
  "console-policy-and-runtime-clean",
]);
const bridgeGates = new Set([
  "fixture-runtime",
  "mp4-api-worker-browser-real-fixture-bytes",
  "native-streamed-browser-download",
  "mp3-preference-keyboard-tabs-and-output",
  "bridge-responsive-authenticated",
  "console-policy-and-runtime-clean",
]);
assert(
  /fixture|packaging/.test(project),
  "Use an explicitly isolated fixture/packaging Compose project",
);
const passwordFile = process.env.SEORAP_BROWSER_PASSWORD_FILE;
assert(passwordFile, "SEORAP_BROWSER_PASSWORD_FILE must name the isolated fixture password file");
const password = (await readFile(passwordFile, "utf8")).trim();
assert(password.length >= 10, "Fixture password file is empty or too short");
const runId = randomUUID().slice(0, 8),
  session = `downloader-${runId}`;
const output = process.env.SEORAP_BROWSER_OUTPUT || `/workspace/screenshots/downloader-${runId}`;
assert(
  resolve(output).startsWith("/workspace/screenshots/"),
  "Screenshots must be under /workspace/screenshots",
);
await mkdir(output, { recursive: true });
await mkdir("/workspace/.cache/agent-browser", { recursive: true });
const env = { ...process.env, AGENT_BROWSER_SOCKET_DIR: "/workspace/.cache/agent-browser" };
const report = {
  kind: "fixture",
  mode: bridgeMode ? "bridge" : stressMode ? "stress" : "full",
  liveYouTube: "skipped: no explicitly permitted LIVE_TEST_URL used",
  baseURL: base.origin,
  runId,
  startedAt: new Date().toISOString(),
  gates: [],
  screenshots: [],
  accessibility: [],
  pageErrors: [],
  consoleErrors: [],
  failedRequests: [],
  externalGrok: [],
  outputs: [],
  nativeDownloads: [],
  consoleDetails: [],
};
const downloads = [];
const nativeTransfers = [];
const completedTransfers = new Set();
const activeEventRequests = new Set();
const stressJobs = [];
let stressSampling = false,
  maximumStressEventRequests = 0,
  activeGate = "";
let catalogOriginal = null,
  catalogPath = null;
let chrome,
  browser,
  context,
  page,
  cookie = "",
  csrf = "";
let port;
const pause = (ms) => new Promise((done) => setTimeout(done, ms));

async function gate(name, work) {
  if (bridgeMode && !bridgeGates.has(name)) {
    report.gates.push({ name, status: "skipped", reason: "Focused Grok bridge profile" });
    return;
  }
  if (stressMode && !stressGates.has(name)) {
    report.gates.push({ name, status: "skipped", reason: "Focused real seven-job queue profile" });
    return;
  }
  const started = Date.now();
  activeGate = name;
  try {
    const details = await work();
    report.gates.push({
      name,
      status: "passed",
      durationMs: Date.now() - started,
      ...(details || {}),
    });
    console.log(JSON.stringify({ gate: name, status: "passed" }));
  } catch (error) {
    report.gates.push({ name, status: "failed", error: error.message });
    throw error;
  } finally {
    activeGate = "";
  }
}

async function atomicCatalog(text) {
  const temporary = `${catalogPath}.browser-${runId}.tmp`;
  await writeFile(temporary, text, { mode: 0o644 });
  // The cloud shell uses a restrictive umask; the fixture container UID differs.
  await chmod(temporary, 0o644);
  await rename(temporary, catalogPath);
}
async function cleanupStress() {
  for (const id of stressJobs) {
    await api(`/jobs/${id}/cancel`, { method: "POST" });
  }
  for (const id of stressJobs) {
    await poll(
      () => api(`/jobs/${id}`),
      (job) => !["queued", "running"].includes(job.status),
      15000,
    );
  }
  stressJobs.length = 0;
  if (catalogOriginal != null) {
    await atomicCatalog(catalogOriginal);
    catalogOriginal = null;
  }
  stressSampling = false;
}
async function poll(work, test, timeout = 60000) {
  const deadline = Date.now() + timeout;
  do {
    const value = await work();
    if (test(value)) return value;
    await pause(200);
  } while (Date.now() < deadline);
  throw new Error("Timed out waiting for fixture state");
}
async function command(args, input) {
  return await new Promise((done, reject) => {
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
    child.stdout.on("data", (chunk) => {
      stdout += chunk;
    });
    child.stderr.on("data", (chunk) => {
      stderr += chunk;
    });
    child.on("error", reject);
    child.on("exit", (code) => {
      if (code)
        return reject(
          new Error(
            `agent-browser ${args[0]} failed: ${(stderr || stdout).replaceAll(password, "[redacted]").slice(-2500)}`,
          ),
        );
      try {
        done(JSON.parse(stdout));
      } catch {
        done(stdout);
      }
    });
    child.stdin.end(input);
  });
}
async function batch(commands) {
  return command(["batch", "--bail"], JSON.stringify(commands));
}
async function evaluate(source) {
  return command(["eval", source]);
}
function check(source, message) {
  return [
    "eval",
    `(() => { if (!(${source})) throw Error(${JSON.stringify(message)}); return true; })()`,
  ];
}
async function api(path, options = {}) {
  const response = await fetch(new URL(`/api/v1${path}`, base), {
    ...options,
    headers: {
      Cookie: cookie,
      Origin: base.origin,
      "X-Requested-With": "seorap",
      "X-CSRF-Token": csrf,
      "X-Locale": "ko",
      "Content-Type": "application/json",
      ...options.headers,
    },
    signal: AbortSignal.timeout(30000),
  });
  assert(
    response.ok,
    `Fixture API ${options.method || "GET"} ${path}: ${response.status} ${(await response.clone().text()).slice(0, 700)}`,
  );
  return response.status === 204 ? null : response.json();
}
async function credentials() {
  const cookies = await context.cookies(base.origin);
  cookie = cookies.map((value) => `${value.name}=${value.value}`).join("; ");
  const value = await api("/auth/session");
  assert(value.authenticated, "Browser is not authenticated");
  csrf = value.csrf_token;
}
async function screenshot(name, fullPage = true) {
  const file = join(output, `${name}.png`);
  await command(["screenshot", file, ...(fullPage ? ["--full"] : [])]);
  report.screenshots.push(file);
}
async function audit(name) {
  const results = await new AxeBuilder({ page })
    .withTags(["wcag2a", "wcag2aa", "wcag21aa"])
    .analyze();
  const violations = results.violations.map((value) => ({
    id: value.id,
    impact: value.impact,
    help: value.help,
    nodes: value.nodes.map((node) => ({ target: node.target, summary: node.failureSummary })),
  }));
  report.accessibility.push({ name, violations });
  assert.equal(
    violations.length,
    0,
    `Accessibility ${name}: ${violations.map((value) => value.id).join(", ")}`,
  );
}
async function fixtureDb(script, parameters) {
  const files = (
    process.env.SEORAP_COMPOSE_FILES ||
    "docker-compose.yml,docker-compose.cloud.yml,docker-compose.fixture.yml"
  ).split(",");
  const args = [
    "compose",
    "-p",
    project,
    ...files.flatMap((file) => ["-f", file]),
    "exec",
    "-T",
    "app",
    "python",
    "-c",
    script,
  ];
  const child = spawn("docker", args, { cwd: root, env, stdio: ["pipe", "pipe", "pipe"] });
  let stdout = "",
    stderr = "";
  child.stdout.on("data", (chunk) => {
    stdout += chunk;
  });
  child.stderr.on("data", (chunk) => {
    stderr += chunk;
  });
  child.stdin.end(JSON.stringify(parameters));
  const code = await new Promise((done, reject) => {
    child.on("error", reject);
    child.on("exit", done);
  });
  assert.equal(code, 0, `Isolated fixture DB helper failed: ${stderr.slice(-1500)}`);
  return stdout ? JSON.parse(stdout) : null;
}
const selectByLabel = (label, value) => [
  "select",
  `.settings-fields label:nth-child(${["언어", "Language"].includes(label) ? 1 : ["화면 모드", "Appearance"].includes(label) ? 2 : 3}) select`,
  String(value),
];
const button = (name) => ["find", "role", "button", "click", "--name", name, "--exact"];
const cardButton = (id, text) => [
  "click",
  `article[data-job-id="${id}"] .job-actions > ${text === "서버 파일 삭제" ? "button.danger-quiet" : text === "이 기기에 받기" ? "button.primary" : text === "서버에 계속 보관" ? "button:nth-of-type(2)" : "button.secondary:first-of-type"}`,
];
async function analyze(videoId, mode = "mp4") {
  await batch([
    ["fill", "#video-url", `https://www.youtube.com/watch?v=${videoId}`],
    button("링크 분석"),
    ["wait", "--fn", '!!document.querySelector(".analysis-result")'],
    [
      "find",
      "role",
      "tab",
      "click",
      "--name",
      mode === "mp4" ? "MP4 영상" : "MP3 오디오",
      "--exact",
    ],
    ["wait", "--fn", `!!document.querySelector('#quality-${mode}')?.value`],
  ]);
}
async function createFromUi(mode = "mp4") {
  const before = new Set((await api("/jobs?limit=100")).jobs.map((job) => job.id));
  await batch([button(mode === "mp4" ? "MP4 만들기" : "MP3 만들기")]);
  return await poll(
    () => api("/jobs?limit=100"),
    (list) => list.jobs.some((job) => !before.has(job.id)),
  ).then((list) => list.jobs.find((job) => !before.has(job.id)));
}
async function waitDone(id) {
  const result = await poll(
    () => api(`/jobs/${id}`),
    (job) => !["queued", "running"].includes(job.status),
  );
  assert.equal(result.status, "succeeded", JSON.stringify(result.error));
  await command([
    "wait",
    "--fn",
    `!!document.querySelector('article[data-job-id="${id}"]')?.textContent.includes('받을 수 있음')`,
  ]);
  return result;
}
async function verifyBytes(job) {
  const response = await fetch(new URL(`/api/v1/jobs/${job.id}/file`, base), {
    headers: { Cookie: cookie },
    signal: AbortSignal.timeout(30000),
  });
  assert.equal(response.status, 200);
  assert.match(response.headers.get("content-disposition"), /filename\*=/);
  const bytes = Buffer.from(await response.arrayBuffer());
  assert.equal(bytes.length, job.artifact.bytes);
  assert(bytes.length > 100);
  const file = join(output, `${job.id}.${job.output.kind === "mp4" ? "mp4" : "mp3"}`);
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
  if (job.output.kind === "mp4") {
    assert(probed.streams.some((stream) => stream.codec_name === "h264"));
    assert(probed.streams.some((stream) => stream.codec_name === "aac"));
  } else {
    assert(probed.streams.every((stream) => stream.codec_type === "audio"));
    assert(probed.streams.some((stream) => stream.codec_name === "mp3"));
    assert(
      probed.streams.some(
        (stream) => Math.abs(Number(stream.bit_rate) - job.output.bitrate_kbps * 1000) <= 1000,
      ),
      "Delivered MP3 bitrate did not match the selected contract",
    );
  }
  report.outputs.push({
    jobId: job.id,
    kind: job.output.kind,
    bytes: bytes.length,
    path: file,
    duration: Number(probed.format.duration),
    streams: probed.streams.map((stream) => ({
      codec: stream.codec_name,
      type: stream.codec_type,
      width: stream.width,
      height: stream.height,
      bitrateBps: stream.bit_rate ? Number(stream.bit_rate) : null,
    })),
  });
}

try {
  await gate("fixture-runtime", async () => {
    // Repeated fault-injection runs share this disposable fixture DB. Start the
    // login-rate fixture with no earlier synthetic failures; operator/secrets stay.
    await fixtureDb(
      "from app.config import load_settings\nfrom app.db import connect\ns=load_settings(); assert s.demo_data and s.allow_test_hooks\nc=connect(s); c.execute('DELETE FROM login_attempts'); c.close()",
      {},
    );
    report.fixtureLoginAttemptSetup =
      "Cleared synthetic login-attempt rows in guarded isolated fixture DB";
    const response = await fetch(new URL("/healthz", base), { signal: AbortSignal.timeout(10000) });
    assert(response.ok);
    const server = createServer();
    await new Promise((done) => server.listen(0, "127.0.0.1", done));
    port = server.address().port;
    await new Promise((done) => server.close(done));
    const profile = join("/workspace/.cache", `browser-${session}`);
    chrome = spawn(
      process.env.CHROMIUM_PATH || "/usr/bin/chromium",
      [
        "--headless",
        "--no-sandbox",
        "--disable-dev-shm-usage",
        `--remote-debugging-port=${port}`,
        `--user-data-dir=${profile}`,
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
    const downloadControl = await browser.newBrowserCDPSession();
    downloadControl.on("Browser.downloadWillBegin", (value) => nativeTransfers.push(value));
    downloadControl.on("Browser.downloadProgress", (value) => {
      if (value.state === "completed") completedTransfers.add(value.guid);
    });
    await downloadControl.send("Browser.setDownloadBehavior", {
      behavior: "allowAndName",
      downloadPath: output,
      eventsEnabled: true,
    });
    const observe = (value) => {
      value.on("download", (download) => downloads.push(download));
      value.on("pageerror", (error) => report.pageErrors.push(error.message));
      value.on("console", (message) => {
        if (message.type() === "error") {
          report.consoleErrors.push(message.text());
          report.consoleDetails.push({
            gate: activeGate,
            message: message.text(),
            location: message.location(),
          });
        }
      });
      value.on("request", (request) => {
        if (new URL(request.url()).pathname.endsWith("/events")) {
          activeEventRequests.add(request);
          if (stressSampling)
            maximumStressEventRequests = Math.max(
              maximumStressEventRequests,
              activeEventRequests.size,
            );
        }
      });
      value.on("requestfinished", (request) => activeEventRequests.delete(request));
      value.on("requestfailed", (request) => {
        activeEventRequests.delete(request);
        const item = { url: request.url(), error: request.failure()?.errorText };
        report.failedRequests.push(item);
        if (item.url.includes("grok.com")) report.externalGrok.push(item);
      });
      value.on("response", (response) => {
        if (response.url().includes("grok.com") && response.status() >= 400)
          report.externalGrok.push({ url: response.url(), status: response.status() });
      });
    };
    context.pages().forEach(observe);
    context.on("page", observe);
    await batch([
      ["open", base.href],
      ["set", "viewport", "1280", "844"],
      ["wait", "--fn", '!!document.querySelector("#local-password")'],
      ...(bridgeMode
        ? []
        : [
            ["fill", "#local-password", "incorrect-fixture-password"],
            button("로그인"),
            ["wait", "--fn", '!!document.querySelector("#local-password[aria-invalid=true]")'],
          ]),
      ["fill", "#local-password", password],
      button("로그인"),
      ["wait", "--fn", '!!document.querySelector("#video-url")'],
    ]);
    page = context.pages().find((value) => value.url().startsWith(base.origin));
    assert(page);
    await credentials();
    const settings = await api("/settings");
    assert.equal(settings.capabilities.demo_data, true, "Refusing non-fixture runtime");
    if (settings.language === "en") {
      await batch([
        button("Settings"),
        selectByLabel("Language", "ko"),
        ["wait", "--fn", 'document.documentElement.lang === "ko"'],
        ["press", "Escape"],
      ]);
    }
    await screenshot("authenticated-desktop");
    await audit("authenticated-empty");
    return { authenticated: true, fixture: true };
  });
  let mp4, mp3, slow;
  await gate("mp4-api-worker-browser-real-fixture-bytes", async () => {
    await analyze("fixH264aacA");
    await screenshot("mp4-analysis");
    await audit("mp4-analysis");
    mp4 = await createFromUi();
    mp4 = await waitDone(mp4.id);
    await verifyBytes(mp4);
    await screenshot("mp4-ready");
  });
  await gate("native-streamed-browser-download", async () => {
    const count = downloads.length;
    const transferCount = nativeTransfers.length;
    await batch([cardButton(mp4.id, "이 기기에 받기")]);
    const download = await poll(async () => downloads[count], Boolean, 15000);
    const transfer = await poll(async () => nativeTransfers[transferCount], Boolean, 15000);
    await poll(async () => completedTransfers.has(transfer.guid), Boolean, 15000);
    const file = join(output, `native-${mp4.id}.mp4`);
    assert.equal(await download.failure(), null);
    // CDP's explicit allowAndName path belongs to this harness. A second CDP
    // observer's Playwright saveAs path can differ; read the completed GUID file.
    const bytes = await readFile(join(output, transfer.guid));
    await writeFile(file, bytes);
    assert.equal(bytes.length, mp4.artifact.bytes);
    const { stdout } = await exec(process.env.FFPROBE_PATH || "ffprobe", [
      "-v",
      "error",
      "-show_streams",
      "-of",
      "json",
      file,
    ]);
    assert(JSON.parse(stdout).streams.some((stream) => stream.codec_name === "h264"));
    report.nativeDownloads.push({
      jobId: mp4.id,
      bytes: bytes.length,
      path: file,
      suggestedFilename: download.suggestedFilename(),
    });
    await batch([
      check('!!document.querySelector("#video-url")', "Native download replaced the app"),
    ]);
  });
  await gate("initial-api-unavailable-recovers-without-browser-reload", async () => {
    // Abort transport only. Responses still come from the real fixture API after recovery.
    await batch([
      ["network", "route", "**/api/v1/**", "--abort"],
      ["reload"],
      ["wait", "--fn", 'document.body.textContent.includes("변환 서버에 연결할 수 없습니다")'],
      ["network", "unroute", "**/api/v1/**"],
      button("다시 확인"),
      ["wait", "--fn", '!!document.querySelector("#video-url")'],
    ]);
    await credentials();
  });
  await gate("mp3-preference-keyboard-tabs-and-output", async () => {
    await batch([button("설정"), ["wait", "--fn", '!!document.querySelector("[role=dialog]")']]);
    const styles = await page.evaluate(() => {
      const nonce = document.querySelector('meta[name="csp-style-nonce"]')?.content;
      const inline = [...document.querySelectorAll("style")];
      return {
        metaPresent: Boolean(nonce),
        inlineStyleCount: inline.length,
        allMatchNonce: inline.every((style) => style.nonce === nonce),
        allHaveAppliedSheets: inline.every((style) => Boolean(style.sheet)),
        bodyOverflow: getComputedStyle(document.body).overflow,
      };
    });
    report.styleNonce = styles;
    if (styles.metaPresent) {
      assert(
        styles.inlineStyleCount > 0 && styles.allMatchNonce && styles.allHaveAppliedSheets,
        "Dialog inline style nonce was absent or rejected",
      );
      assert.equal(
        styles.bodyOverflow,
        "hidden",
        "Nonce-protected modal scroll lock did not apply",
      );
    }
    await batch([
      selectByLabel("기본 MP3 비트레이트", 320),
      [
        "wait",
        "--fn",
        '!document.querySelector(".settings-fields")?.getAttribute("aria-busy")?.includes("true")',
      ],
      ["press", "Escape"],
      ["wait", "--fn", 'document.activeElement?.getAttribute("aria-label") === "설정"'],
      ["focus", '[role="tab"][data-state="active"]'],
      ["press", "ArrowRight"],
      [
        "wait",
        "--fn",
        'document.querySelector("[role=tab][aria-selected=true]")?.textContent.includes("MP3")',
      ],
      check(
        'document.querySelector("[role=tab][aria-selected=true]")?.textContent.includes("MP3")',
        "Keyboard tab selection failed",
      ),
    ]);
    await analyze("fixH264aacA", "mp3");
    await batch([
      check(
        'document.querySelector("#quality-mp3")?.selectedOptions[0]?.textContent.includes("320")',
        "Saved bitrate not applied",
      ),
    ]);
    mp3 = await createFromUi("mp3");
    mp3 = await waitDone(mp3.id);
    assert.equal(mp3.output.bitrate_kbps, 320);
    await verifyBytes(mp3);
    await screenshot("mp3-ready");
    await audit("mp3-ready");
  });
  await gate("active-job-refresh-and-reconnect", async () => {
    await analyze("fixSleepAAA");
    slow = await createFromUi();
    assert(
      ["queued", "running"].includes(slow.status),
      "Slow fixture completed before active reload could be exercised",
    );
    await batch([["reload"], ["wait", "--fn", '!!document.querySelector("#video-url")']]);
    await credentials();
    slow = await waitDone(slow.id);
    await verifyBytes(slow);
    await command(["set", "offline", "on"]);
    await pause(800);
    await command(["set", "offline", "off"]);
    await command([
      "wait",
      "--fn",
      '!document.querySelector(".connection-state")?.textContent.includes("오프라인")',
    ]);
    return { restoredJobId: slow.id };
  });
  await gate("file-pin-delete-confirmation-and-expired-recovery", async () => {
    await batch([cardButton(mp4.id, "서버에 계속 보관")]);
    await poll(
      () => api(`/jobs/${mp4.id}`),
      (job) => job.keep_on_server,
    );
    await batch([
      cardButton(slow.id, "서버 파일 삭제"),
      ["wait", "--fn", '!!document.querySelector("[role=alertdialog]")'],
    ]);
    assert.equal(
      (await api(`/jobs/${slow.id}`)).file_state,
      "available",
      "Delete must require confirmation",
    );
    await audit("file-delete-confirmation");
    await batch([button("돌아가기")]);
    await batch([cardButton(slow.id, "서버 파일 삭제"), button("파일 영구 삭제")]);
    await poll(
      () => api(`/jobs/${slow.id}`),
      (job) => job.file_state === "deleted",
    );
    await fixtureDb(
      `import json,sys\nfrom app.config import load_settings\nfrom app.db import connect,utc_iso,utc_now\nfrom datetime import timedelta\ns=load_settings(); assert s.demo_data and s.allow_test_hooks\np=json.load(sys.stdin); c=connect(s); c.execute("UPDATE jobs SET keep_on_server=0,file_expires_at=? WHERE id=?",(utc_iso(utc_now()-timedelta(seconds=1)),p['id'])); c.close()`,
      { id: mp3.id },
    );
    await batch([
      cardButton(mp3.id, "이 기기에 받기"),
      [
        "wait",
        "--fn",
        `document.querySelector('article[data-job-id="${mp3.id}"]')?.textContent.includes('만료')`,
      ],
      check(
        "location.origin === " +
          JSON.stringify(base.origin) +
          ' && !!document.querySelector("#video-url")',
        "Expired download stranded the app",
      ),
    ]);
    assert.equal((await api(`/jobs/${mp3.id}`)).file_state, "expired");
    await screenshot("expired-recovery");
  });
  await gate("cancel-and-explicit-parent-retry", async () => {
    await analyze("fixSleepAAA");
    const cancelled = await createFromUi();
    await batch([cardButton(cancelled.id, "작업 취소")]);
    await poll(
      () => api(`/jobs/${cancelled.id}`),
      (job) => job.status === "cancelled",
    );
    await command([
      "wait",
      "--fn",
      `!!document.querySelector('article[data-job-id="${cancelled.id}"]')?.textContent.includes('다시 분석해 만들기')`,
    ]);
    await batch([
      cardButton(cancelled.id, "다시 분석해 만들기"),
      check(
        'document.querySelector("#video-url")?.value.includes("fixSleepAAA")',
        "Retry did not preserve source",
      ),
    ]);
    await analyze("fixSleepAAA");
    const retried = await createFromUi();
    assert.equal(retried.parent_job_id, cancelled.id);
    await verifyBytes(await waitDone(retried.id));
  });
  await gate("actual-result-seven-job-queue-responsive-dialogs-and-playlist", async () => {
    assert(
      process.env.SEORAP_FIXTURE_DIR,
      "SEORAP_FIXTURE_DIR is required for controlled long fixture work",
    );
    catalogPath = join(resolve(process.env.SEORAP_FIXTURE_DIR), "catalog.json");
    catalogOriginal = await readFile(catalogPath, "utf8");
    const catalog = JSON.parse(catalogOriginal);
    assert(
      catalog.fixSleepAAA?.file?.startsWith("/fixtures/"),
      "Only generated fixture catalog media is allowed",
    );
    catalog.fixSleepAAA.sleep_seconds = 300;
    catalog.fixSleepAAA.title =
      "실제 합성 미디어 대기열 · 아주 긴 한국어 제목과 English words ".repeat(6);
    await atomicCatalog(JSON.stringify(catalog));
    try {
      await analyze("fixSleepAAA");
      const analysis = await api("/analyses", {
        method: "POST",
        body: JSON.stringify({ url: "https://www.youtube.com/watch?v=fixSleepAAA" }),
      });
      const selected =
        analysis.choices.find((choice) => choice.kind === "mp4" && choice.is_default) ||
        analysis.choices.find((choice) => choice.kind === "mp4");
      assert(selected);
      assert.equal(
        (await api("/jobs?active=true&limit=100")).jobs.length,
        0,
        "Earlier fixture work did not stop before queue stress",
      );
      report.preStressObserverRequestCount = activeEventRequests.size;
      // Requests from a destroyed/reloaded page can miss the observer's finish
      // event. Sample this phase separately, and count live real EventSources.
      activeEventRequests.clear();
      maximumStressEventRequests = 0;
      await evaluate(`(() => {
        const Native = window.EventSource;
        const state = window.__fixtureSse = { instances: new Set(), maximum: 0 };
        window.EventSource = class extends Native {
          constructor(...args) { super(...args); state.instances.add(this); state.maximum = Math.max(state.maximum, state.instances.size); }
          close() { super.close(); state.instances.delete(this); }
        };
        window.__restoreFixtureSse = () => { window.EventSource = Native; };
      })()`);
      stressSampling = true;
      for (let index = 0; index < 7; index++) {
        const job = await api("/jobs", {
          method: "POST",
          headers: { "Idempotency-Key": `browser-${runId}-queue-${index}` },
          body: JSON.stringify({
            analysis_id: analysis.analysis_id,
            choice_id: selected.choice_id,
            keep_on_server: false,
            conversion_consent: false,
          }),
        });
        stressJobs.push(job.id);
      }
      await command([
        "wait",
        "--fn",
        'document.querySelectorAll(".jobs-section article[data-job-id]").length >= 7',
      ]);
      for (const width of [320, 390, 768, 1280]) {
        await command(["set", "viewport", String(width), "844"]);
        await batch([
          check(
            '!!document.querySelector(".analysis-result") && document.querySelectorAll(".jobs-section article[data-job-id]").length >= 7',
            "Actual result or seven-job queue disappeared",
          ),
          check(
            "document.documentElement.scrollWidth <= innerWidth + 1",
            `Active queue overflow at ${width}`,
          ),
        ]);
        await screenshot(`actual-result-queue-${width}`);
        await audit(`actual-result-queue-${width}`);
        if (width <= 390) {
          await evaluate(
            'document.querySelector(".analysis-result").scrollIntoView({ block: "start" })',
          );
          await screenshot(`actual-result-${width}-viewport`, false);
          await evaluate(
            'document.querySelector(".jobs-section").scrollIntoView({ block: "start" })',
          );
          await screenshot(`actual-queue-${width}-viewport`, false);
          await batch([
            button("설정"),
            ["wait", "--fn", '!!document.querySelector("[role=dialog]")'],
            selectByLabel("화면 모드", width === 320 ? "dark" : "system"),
            [
              "wait",
              "--fn",
              'document.querySelector(".settings-fields")?.getAttribute("aria-busy") === "false"',
            ],
          ]);
          assert.equal(
            (await api("/settings")).theme,
            width === 320 ? "dark" : "system",
            "Preference mutation starved behind active jobs",
          );
          await screenshot(`settings-active-${width}`);
          await screenshot(`settings-active-${width}-viewport`, false);
          await audit(`settings-active-${width}`);
          await batch([
            ["press", "Tab"],
            check(
              '!!document.activeElement?.closest("[role=dialog]")',
              "Narrow settings focus escaped",
            ),
            ["press", "Escape"],
          ]);
        }
      }
      await command(["set", "viewport", "1280", "900"]);
      const beforeZoom = await page.evaluate(() => ({ innerWidth, devicePixelRatio }));
      await batch(Array.from({ length: 5 }, () => ["press", "Control+Equal"]));
      const afterZoom = await page.evaluate(() => ({ innerWidth, devicePixelRatio }));
      const nativeZoomWorked =
        afterZoom.innerWidth <= beforeZoom.innerWidth * 0.6 ||
        afterZoom.devicePixelRatio >= beforeZoom.devicePixelRatio * 1.8;
      report.nativeBrowserZoom = {
        before: beforeZoom,
        after: afterZoom,
        status: nativeZoomWorked
          ? "native-keyboard-zoom-observed"
          : "unsupported-by-headless-keyboard; CSS zoom and narrow viewport tested; native browser zoom manual run skipped",
      };
      if (nativeZoomWorked) {
        await screenshot("actual-result-queue-native-zoom");
        await audit("actual-result-queue-native-zoom");
      }
      await command(["press", "Control+0"]);
      await evaluate('document.body.style.zoom = "2"');
      await batch([
        check(
          "document.documentElement.scrollWidth <= innerWidth + 1",
          "Active queue overflow at 200% CSS zoom",
        ),
      ]);
      await screenshot("actual-result-queue-200pct");
      await audit("actual-result-queue-200pct");
      await evaluate('document.body.style.zoom = ""');
      await batch([
        ["click", ".playlist-section > summary"],
        ["fill", "#playlist-url", "https://www.youtube.com/playlist?list=PLFIXTURE1"],
        button("목록 살펴보기"),
        ["wait", "--fn", 'document.querySelectorAll(".playlist-entries li").length === 20'],
      ]);
      await screenshot("actual-playlist-limited");
      await audit("actual-playlist-limited");
      await command(["click", ".playlist-entries li:first-child button"]);
      await batch([
        check(
          'document.activeElement?.id === "video-url"',
          "Playlist selection did not focus the URL",
        ),
        check(
          'document.querySelector("#video-url")?.value.includes("watch?v=")',
          "Playlist selection did not transfer an actual URL",
        ),
      ]);
      const maximumOwnedStreams = await page.evaluate(() => window.__fixtureSse.maximum);
      assert(maximumOwnedStreams <= 2, `Observed ${maximumOwnedStreams} live owned EventSources`);
      return {
        actualJobsCreated: stressJobs.length,
        maximumObservedNetworkRequestObjects: maximumStressEventRequests,
        maximumLiveOwnedEventSources: maximumOwnedStreams,
        settingsResponsiveAt320And390: true,
        actualPreferenceMutationsDuringSevenJobs: 2,
      };
    } finally {
      await cleanupStress();
      await evaluate("window.__restoreFixtureSse?.()");
    }
  });
  await gate("history-over-30-and-older-kept-search", async () => {
    const seeded = await fixtureDb(
      `import json,sys,secrets\nfrom app.config import load_settings\nfrom app.db import connect,transaction,utc_iso,utc_now\nfrom datetime import timedelta\ns=load_settings(); assert s.demo_data and s.allow_test_hooks\np=json.load(sys.stdin); c=connect(s); r=c.execute('SELECT * FROM jobs WHERE id=?',(p['id'],)).fetchone(); assert r and r['keep_on_server']\nsource=json.loads(r['source_json']); source['title']=p['title']; old=utc_iso(utc_now()-timedelta(days=2)); now=utc_iso()\nwith transaction(c):\n c.execute('UPDATE jobs SET source_json=?,created_at=?,revision=revision+1 WHERE id=?',(json.dumps(source),old,p['id']))\n for i in range(35):\n  source2={**source,'title':f'합성 기록 {i} · metadata only'}\n  c.execute("INSERT INTO jobs(id,status,file_state,revision,contract_json,source_json,created_at,updated_at,finished_at) VALUES (?,'cancelled','none',1,?,?,?,?,?)",(secrets.token_hex(16),r['contract_json'],json.dumps(source2),now,now,now))\nprint(json.dumps({'seededCancelledMetadata':35})); c.close()`,
      {
        id: mp4.id,
        title: `회귀 테스트 오래된 보관 파일 ${"아주 긴 한국어 제목과 English words ".repeat(8)}`,
      },
    );
    await batch([["reload"], ["wait", "--fn", '!!document.querySelector("#history-search")']]);
    await batch([
      ["fill", "#history-search", "회귀 테스트 오래된 보관 파일"],
      button("검색"),
      ["wait", "--fn", `!!document.querySelector('article[data-job-id="${mp4.id}"]')`],
    ]);
    await screenshot("history-older-kept");
    return seeded;
  });
  await gate("settings-localization-theme-keyboard-and-responsive-axe", async () => {
    await batch([button("설정"), selectByLabel("화면 모드", "dark")]);
    await command(["wait", "--fn", 'document.documentElement.dataset.theme === "dark"']);
    await screenshot("settings-dark");
    await audit("settings-dialog");
    await batch([
      selectByLabel("언어", "en"),
      ["wait", "--fn", 'document.documentElement.lang === "en"'],
      selectByLabel("Language", "ko"),
      ["wait", "--fn", 'document.documentElement.lang === "ko"'],
      selectByLabel("화면 모드", "system"),
      ["press", "Tab"],
      check('!!document.activeElement?.closest("[role=dialog]")', "Dialog focus escaped"),
      ["press", "Escape"],
    ]);
    for (const width of [320, 390, 768, 1280]) {
      await command(["set", "viewport", String(width), "844"]);
      await batch([
        check(
          "document.documentElement.scrollWidth <= innerWidth + 1",
          `Horizontal overflow at ${width}`,
        ),
      ]);
      await screenshot(`authenticated-${width}`);
      await audit(`authenticated-${width}`);
    }
    await command(["set", "viewport", "1280", "900"]);
    await evaluate('document.body.style.zoom = "2"');
    await batch([
      check(
        "document.documentElement.scrollWidth <= innerWidth + 1",
        "Horizontal overflow at 200% zoom",
      ),
    ]);
    await screenshot("authenticated-200pct");
    await audit("authenticated-200pct");
    await evaluate('document.body.style.zoom = ""');
    await context.clearPermissions();
    await evaluate(
      'Object.defineProperty(navigator.clipboard, "readText", { configurable: true, value: async () => { throw new DOMException("Denied", "NotAllowedError"); } })',
    );
    await batch([
      button("붙여넣기"),
      ["wait", "--fn", 'document.body.textContent.includes("주소 칸에 직접 붙여")'],
    ]);
  });
  await gate("mobile-signout-and-session-recovery", async () => {
    await command(["set", "viewport", "390", "844"]);
    await batch([
      button("로그아웃"),
      ["wait", "--fn", '!!document.querySelector("#local-password")'],
      ["fill", "#local-password", password],
      button("로그인"),
      ["wait", "--fn", '!!document.querySelector("#video-url")'],
    ]);
    await credentials();
    assert.equal((await api("/settings")).mp3_bitrate, 320);
    await api("/auth/logout", { method: "POST" });
    await batch([
      button("새로고침"),
      ["wait", "--fn", '!!document.querySelector("#local-password")'],
      ["fill", "#local-password", password],
      button("로그인"),
      ["wait", "--fn", '!!document.querySelector("#video-url")'],
    ]);
    await credentials();
    await screenshot("mobile-signed-in-again");
  });
  if (bridgeMode) {
    await gate("bridge-responsive-authenticated", async () => {
      for (const width of [1280, 390]) {
        await command(["set", "viewport", String(width), "844"]);
        await batch([
          check(
            "document.documentElement.scrollWidth <= innerWidth + 1",
            `Horizontal overflow at ${width}`,
          ),
        ]);
        await screenshot(`bridge-authenticated-${width}`);
        await audit(`bridge-authenticated-${width}`);
      }
    });
  }
  const treePath = join(output, "accessible-tree.json");
  await writeFile(treePath, JSON.stringify(await command(["snapshot", "-i"]), null, 2));
  report.accessibleTree = treePath;
  report.screenReaderScope = "Accessible-name/tree and keyboard smoke; no real NVDA/VoiceOver run";
  await gate("console-policy-and-runtime-clean", async () => {
    const expected = (item) => {
      const url = item.location?.url || "";
      if (url.includes("grok.com")) return true; // separately reported external dependency gate
      if (
        item.gate === "fixture-runtime" &&
        /status of 401/.test(item.message) &&
        url.includes("/auth/login")
      )
        return true;
      if (
        item.gate === "initial-api-unavailable-recovers-without-browser-reload" &&
        /net::ERR_FAILED/.test(item.message) &&
        url.includes("/api/v1/")
      )
        return true;
      if (
        item.gate === "active-job-refresh-and-reconnect" &&
        /net::ERR_INTERNET_DISCONNECTED|net::ERR_NETWORK_CHANGED/.test(item.message) &&
        url.includes("/api/v1/")
      )
        return true;
      if (
        item.gate === "file-pin-delete-confirmation-and-expired-recovery" &&
        /status of 410/.test(item.message) &&
        url.includes("/file")
      )
        return true;
      if (
        item.gate === "mobile-signout-and-session-recovery" &&
        /status of 401/.test(item.message) &&
        url.includes("/api/v1/")
      )
        return true;
      return false;
    };
    report.expectedConsoleErrors = report.consoleDetails.filter(expected);
    report.unexpectedConsoleErrors = report.consoleDetails.filter((item) => !expected(item));
    assert.equal(
      report.unexpectedConsoleErrors.length,
      0,
      JSON.stringify(report.unexpectedConsoleErrors),
    );
  });
  assert.equal(
    report.pageErrors.length,
    0,
    `Uncaught browser errors: ${report.pageErrors.join("; ")}`,
  );
  report.ok = true;
} catch (error) {
  report.ok = false;
  report.error = String(error.message).replaceAll(password, "[redacted]");
  if (page) {
    try {
      await screenshot("failure");
    } catch {
      /* primary failure remains in report */
    }
  }
} finally {
  if (stressJobs.length || catalogOriginal != null) {
    try {
      await cleanupStress();
    } catch (error) {
      report.cleanupError = error.message;
      report.ok = false;
    }
  }
  report.finishedAt = new Date().toISOString();
  await writeFile(join(output, "verification.json"), JSON.stringify(report, null, 2));
  console.log(
    JSON.stringify(
      {
        ok: report.ok,
        report: join(output, "verification.json"),
        gates: report.gates,
        screenshots: report.screenshots,
        outputs: report.outputs,
        pageErrors: report.pageErrors,
        externalGrok: report.externalGrok,
      },
      null,
      2,
    ),
  );
  try {
    await command(["close"]);
  } catch {
    /* Chrome is terminated explicitly below */
  }
  if (browser) await browser.close();
  if (chrome) chrome.kill("SIGTERM");
  process.exitCode = report.ok ? 0 : 1;
}
