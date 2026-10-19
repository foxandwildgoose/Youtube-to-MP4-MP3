#!/usr/bin/env node
/** Real built hosted UI → HTTPS fixture app. No remote deployment or YouTube call.
 * Requires the isolated TLS fixture and its public CA/leaf + password file.
 * agent-browser drives all interaction; Playwright only observes and audits CDP.
 */
import assert from "node:assert/strict";
import { spawn, execFile } from "node:child_process";
import { createHash, X509Certificate, randomUUID } from "node:crypto";
import { readFile, writeFile, mkdir, unlink, copyFile } from "node:fs/promises";
import { request as httpsRequest } from "node:https";
import { createServer, createConnection } from "node:net";
import { join, resolve } from "node:path";
import { promisify } from "node:util";
import { chromium } from "playwright";
import AxeBuilder from "@axe-core/playwright";

const exec = promisify(execFile);
const root = resolve(import.meta.dirname, "..");
const frontend = "http://127.0.0.1:8081";
const app = new URL("https://conversion.example.com:18443");
const password = (
  await readFile(
    process.env.SEORAP_HTTPS_PASSWORD_FILE || "/tmp/seorap-https-fixture-password",
    "utf8",
  )
).trim();
assert(password.length >= 10, "Explicit isolated fixture password file is required");
const ca = await readFile(process.env.SEORAP_HTTPS_CA_FILE || "/tmp/seorap-https-fixture-root.crt");
const leaf = new X509Certificate(
  await readFile(process.env.SEORAP_HTTPS_LEAF_FILE || "/tmp/seorap-https-fixture-leaf.crt"),
);
assert(leaf.checkHost(app.hostname), "Fixture leaf does not identify the exact test hostname");
const spki = createHash("sha256")
  .update(leaf.publicKey.export({ type: "spki", format: "der" }))
  .digest("base64");
const runId = randomUUID().slice(0, 8);
const session = `hosted-${runId}`;
const output = resolve(
  process.env.SEORAP_HOSTED_OUTPUT || `/workspace/screenshots/hosted-${runId}`,
);
assert(output.startsWith("/workspace/screenshots/"));
await mkdir(output, { recursive: true });
try {
  const previous = JSON.parse(await readFile(join(output, "verification.json"), "utf8"));
  await mkdir(join(output, "attempts"), { recursive: true });
  await copyFile(
    join(output, "verification.json"),
    join(output, "attempts", `${previous.runId}.json`),
  );
} catch (error) {
  if (error.code !== "ENOENT") throw error;
}
await mkdir("/workspace/.cache/agent-browser", { recursive: true });
const env = { ...process.env, AGENT_BROWSER_SOCKET_DIR: "/workspace/.cache/agent-browser" };
const networkPolicy = JSON.parse(await readFile("/etc/codex/network-policy.json", "utf8"));
const sessionProxy = new URL(networkPolicy.http_proxy);
assert(
  ["http:", "https:"].includes(sessionProxy.protocol) &&
    !sessionProxy.username &&
    !sessionProxy.password,
  "Use only the managed session's public proxy address",
);
const report = {
  runId,
  kind: "compiled-hosted-ui-to-isolated-https-fixture",
  startedAt: new Date().toISOString(),
  liveYouTube: "skipped: no permitted LIVE_TEST_URL used",
  gates: [],
  screenshots: [],
  accessibility: [],
  responses: [],
  consoleErrors: [],
  pageErrors: [],
  failedRequests: [],
  externalGrok: [],
  outputs: [],
  nativeDownloads: [],
  redirects: [],
};
try {
  await readFile(join(output, "harness-repair-history.json"), "utf8");
  report.harnessRepairHistory = join(output, "harness-repair-history.json");
} catch (error) {
  if (error.code !== "ENOENT") throw error;
}
let activeGate = "",
  chrome,
  browser,
  context,
  page,
  port,
  qaStarted = false,
  cookie = "",
  csrf = "";
const transfers = [],
  completed = new Set();
const pause = (ms) => new Promise((done) => setTimeout(done, ms));
async function poll(work, condition, timeout = 45000) {
  const deadline = Date.now() + timeout;
  do {
    const value = await work();
    if (condition(value)) return value;
    await pause(200);
  } while (Date.now() < deadline);
  throw Error("Timed out waiting for actual fixture/browser state");
}
async function gate(name, work) {
  activeGate = name;
  const started = Date.now();
  try {
    const facts = await work();
    report.gates.push({
      name,
      status: "passed",
      durationMs: Date.now() - started,
      ...(facts || {}),
    });
    console.log(JSON.stringify({ gate: name, status: "passed" }));
  } catch (error) {
    report.gates.push({
      name,
      status: "failed",
      error: error.message.replaceAll(password, "[redacted]"),
    });
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
        return reject(
          Error(
            `agent-browser ${args[0]}: ${(stderr || stdout).replaceAll(password, "[redacted]").slice(-2300)}`,
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
const batch = (commands) => agent(["batch", "--bail"], JSON.stringify(commands));
const button = (name) => ["find", "role", "button", "click", "--name", name, "--exact"];
const check = (source, message) => [
  "eval",
  `(() => {if (!(${source})) throw Error(${JSON.stringify(message)}); return true})()`,
];
async function screenshot(name) {
  const file = join(output, name + ".png");
  await agent(["screenshot", file]);
  report.screenshots.push(file);
}
async function audit(name) {
  const result = await new AxeBuilder({ page })
    .withTags(["wcag2a", "wcag2aa", "wcag21aa"])
    .analyze();
  const violations = result.violations.map((v) => ({
    id: v.id,
    impact: v.impact,
    nodes: v.nodes.map((n) => n.target),
  }));
  report.accessibility.push({ name, violations });
  assert.equal(violations.length, 0, `Axe ${name}: ${JSON.stringify(violations)}`);
}
async function personalSnapshot() {
  const { stdout } = await exec(
    join(root, ".venv/bin/python"),
    [
      "-c",
      "import json,sqlite3,pathlib,importlib.util; r=pathlib.Path.cwd();s=importlib.util.spec_from_file_location('p',r/'scripts/preview-runtime.py');m=importlib.util.module_from_spec(s);s.loader.exec_module(m);c=sqlite3.connect('file:data/state/app.db?mode=ro',uri=True);print(json.dumps({'operator':c.execute('SELECT id,created_at,updated_at FROM operator ORDER BY id').fetchall(),'jobs':c.execute('SELECT count(*) FROM jobs').fetchone()[0],'owned':{n:m.owned_runner(r/'data/state'/('preview-'+n+'.json')) for n in ('api','web','worker')},'worker':m.worker_state(r/'data'),'api':m.http_ready('http://127.0.0.1:8000/healthz'),'web':m.http_ready('http://127.0.0.1:8080/')}))",
    ],
    { cwd: root },
  );
  const snapshot = JSON.parse(stdout);
  snapshot.runners = Object.fromEntries(
    await Promise.all(
      ["api", "web", "worker"].map(async (name) => {
        const record = JSON.parse(
          await readFile(join(root, "data/state", `preview-${name}.json`), "utf8"),
        );
        return [name, { pid: record.pid, start_ticks: record.start_ticks }];
      }),
    ),
  );
  return snapshot;
}
async function portOpen(value) {
  return new Promise((done) => {
    const socket = createConnection({ host: "127.0.0.1", port: value });
    socket.once("connect", () => {
      socket.destroy();
      done(true);
    });
    socket.once("error", () => {
      socket.destroy();
      done(false);
    });
    socket.setTimeout(1500, () => {
      socket.destroy();
      done(false);
    });
  });
}
async function restart(configured) {
  const variables = { ...env, SEORAP_DEPLOYMENT: "hosted" };
  delete variables.SEORAP_APP_ORIGIN;
  if (configured) variables.SEORAP_APP_ORIGIN = app.origin;
  const result = await exec("npm", ["run", "preview:restart"], {
    cwd: root,
    env: variables,
    timeout: 65000,
    maxBuffer: 100000,
  });
  qaStarted = true;
  assert.match(result.stdout, /ready|8081/i);
}
async function tls(path, options = {}) {
  return new Promise((done, reject) => {
    const req = httpsRequest(
      new URL(path, app),
      {
        ca,
        rejectUnauthorized: true,
        lookup: (_host, options, callback) =>
          options.all
            ? callback(null, [{ address: "127.0.0.1", family: 4 }])
            : callback(null, "127.0.0.1", 4),
        method: options.method || "GET",
        headers: {
          Cookie: cookie,
          Origin: app.origin,
          "X-Requested-With": "seorap",
          "X-CSRF-Token": csrf,
          "Content-Type": "application/json",
          ...options.headers,
        },
      },
      (res) => {
        const chunks = [];
        res.on("data", (chunk) => chunks.push(chunk));
        res.on("error", reject);
        res.on("end", () =>
          done({ status: res.statusCode, headers: res.headers, body: Buffer.concat(chunks) }),
        );
      },
    );
    req.setTimeout(30000, () => req.destroy(Error("TLS fixture request timeout")));
    req.on("error", reject);
    if (options.body) req.write(JSON.stringify(options.body));
    req.end();
  });
}
async function api(path, options) {
  const result = await tls("/api/v1" + path, options);
  assert(
    result.status >= 200 && result.status < 300,
    `TLS API ${path}: ${result.status} ${result.body.toString().slice(0, 700)}`,
  );
  return result.body.length ? JSON.parse(result.body) : null;
}
async function setLanguage(language) {
  const current = await page.locator("html").getAttribute("lang");
  await batch([
    button(current === "en" ? "Settings" : "설정"),
    ["select", ".settings-fields label:nth-child(1) select", language],
    ["wait", "--fn", `document.documentElement.lang===${JSON.stringify(language)}`],
    ["press", "Escape"],
  ]);
}
async function analyze(mode) {
  await batch([
    ["fill", "#video-url", "https://www.youtube.com/watch?v=fixH264aacA"],
    button("링크 분석"),
    ["wait", "--fn", "!!document.querySelector('.analysis-result')"],
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
async function createJob(mode) {
  const before = new Set((await api("/jobs?limit=100")).jobs.map((j) => j.id));
  await batch([button(mode === "mp4" ? "MP4 만들기" : "MP3 만들기")]);
  let job = await poll(
    () => api("/jobs?limit=100"),
    (list) => list.jobs.some((j) => !before.has(j.id)),
  ).then((list) => list.jobs.find((j) => !before.has(j.id)));
  job = await poll(
    () => api(`/jobs/${job.id}`),
    (j) => !["queued", "running"].includes(j.status),
  );
  assert.equal(job.status, "succeeded", JSON.stringify(job.error));
  assert.equal(
    job.output.kind,
    mode,
    "Completed job must match the format requested through the UI",
  );
  await agent([
    "wait",
    "--fn",
    `!!document.querySelector('article[data-job-id="${job.id}"]')?.textContent.includes('받을 수 있음')`,
  ]);
  return job;
}
async function verifyOutput(job, native = false) {
  let bytes, file;
  if (native) {
    const before = transfers.length;
    await batch([["click", `article[data-job-id="${job.id}"] .job-actions > button.primary`]]);
    const transfer = await poll(async () => transfers[before], Boolean, 15000);
    await poll(async () => completed.has(transfer.guid), Boolean, 15000);
    assert.equal(new URL(transfer.url).origin, app.origin);
    assert.equal(
      new URL(transfer.url).pathname,
      `/api/v1/jobs/${job.id}/file`,
      "Native browser transfer must belong to the exact newly created job",
    );
    bytes = await readFile(join(output, transfer.guid));
    file = join(output, `native-${job.id}.${job.output.kind}`);
  } else {
    const response = await tls(`/api/v1/jobs/${job.id}/file`);
    assert.equal(response.status, 200);
    bytes = response.body;
    file = join(output, `${job.id}.${job.output.kind}`);
  }
  assert.equal(bytes.length, job.artifact.bytes);
  assert(bytes.length > 100);
  await writeFile(file, bytes);
  const { stdout } = await exec("ffprobe", [
    "-v",
    "error",
    "-show_format",
    "-show_streams",
    "-of",
    "json",
    file,
  ]);
  const probe = JSON.parse(stdout);
  assert(Number(probe.format.duration) > 0);
  if (job.output.kind === "mp4") {
    assert(probe.streams.some((s) => s.codec_name === "h264"));
    assert(probe.streams.some((s) => s.codec_name === "aac"));
  } else {
    assert(probe.streams.every((s) => s.codec_type === "audio"));
    assert(probe.streams.some((s) => s.codec_name === "mp3"));
  }
  (native ? report.nativeDownloads : report.outputs).push({
    jobId: job.id,
    kind: job.output.kind,
    bytes: bytes.length,
    file,
    duration: Number(probe.format.duration),
    streams: probe.streams.map((s) => ({
      codec: s.codec_name,
      type: s.codec_type,
      bitrate: Number(s.bit_rate) || null,
    })),
  });
}

const before = await personalSnapshot();
assert(
  before.api &&
    before.web &&
    before.worker === "ready" &&
    Object.values(before.owned).every(Boolean),
  "Personal preview must be healthy before QA",
);
try {
  await gate("owned-built-hosted-preview-and-pinned-local-tls", async () => {
    assert.equal(await portOpen(8081), false, "Refuse to replace another QA8081 owner");
    const health = await tls("/healthz");
    assert.equal(health.status, 200);
    await restart(false);
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
        "--host-resolver-rules=MAP conversion.example.com 127.0.0.1",
        // This exact fixture hostname resolves only to our own loopback above.
        // Other destinations retain the inherited system proxy and TLS policy.
        "--proxy-bypass-list=conversion.example.com",
        `--proxy-server=${sessionProxy.origin}`,
        `--ignore-certificate-errors-spki-list=${spki}`,
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
    const downloads = await browser.newBrowserCDPSession();
    downloads.on("Browser.downloadWillBegin", (value) => transfers.push(value));
    downloads.on("Browser.downloadProgress", (value) => {
      if (value.state === "completed") completed.add(value.guid);
    });
    await downloads.send("Browser.setDownloadBehavior", {
      behavior: "allowAndName",
      downloadPath: output,
      eventsEnabled: true,
    });
    const observe = (p) => {
      p.on("pageerror", (error) =>
        report.pageErrors.push({ gate: activeGate, message: error.message }),
      );
      p.on("console", (message) => {
        if (message.type() === "error")
          report.consoleErrors.push({
            gate: activeGate,
            message: message.text(),
            location: message.location(),
          });
      });
      p.on("requestfailed", (request) => {
        const item = { url: request.url(), error: request.failure()?.errorText, gate: activeGate };
        report.failedRequests.push(item);
        if (new URL(item.url).hostname === "grok.com") report.externalGrok.push(item);
      });
      p.on("response", async (response) => {
        const url = new URL(response.url());
        if (url.origin === frontend && url.pathname.startsWith("/api/")) {
          let code;
          try {
            code = (await response.json()).error?.code;
          } catch {
            /* not JSON */
          }
          report.responses.push({
            gate: activeGate,
            url: response.url(),
            status: response.status(),
            code,
          });
        }
        if (response.status() === 307)
          report.redirects.push({
            from: response.url(),
            location: response.headers().location,
            navigation: response.request().isNavigationRequest(),
          });
        if (url.hostname === "grok.com" && response.status() >= 400)
          report.externalGrok.push({ url: response.url(), status: response.status() });
      });
    };
    context.pages().forEach(observe);
    context.on("page", observe);
    await batch([
      ["open", frontend],
      ["set", "viewport", "1280", "844"],
      [
        "wait",
        "--fn",
        "document.querySelector('#main-task h2')?.textContent.includes('연결이 아직 완료되지')",
      ],
    ]);
    page = context.pages().find((p) => p.url().startsWith(frontend));
    assert(page);
    return {
      tlsVerification:
        "Node CERT_REQUIRED, public fixture CA + hostname; Chromium exception restricted to owned fixture leaf SPKI",
      backendOrigin: app.origin,
    };
  });
  await gate("missing-config-localized-desktop-mobile-accessible-manual-retry", async () => {
    await batch([
      check(
        "!document.querySelector('#local-password') && !document.querySelector('#video-url')",
        "Unconfigured hosted UI must not offer login or creation",
      ),
      check(
        "!document.querySelector('#main-task')?.textContent.includes('CSRF')",
        "Must not blame user CSRF",
      ),
    ]);
    await screenshot("missing-config-ko-desktop");
    await audit("missing-ko-desktop");
    await poll(
      async () => report.responses,
      (rows) => rows.length > 0,
    );
    await batch([
      check(
        "document.querySelector('#main-task')?.textContent.includes('DEPLOYMENT_NOT_CONFIGURED')",
        "Actual browser did not receive the missing configuration code",
      ),
    ]);
    const missingContract = await fetch(frontend + "/api/v1/auth/session", { redirect: "manual" });
    const missingBody = await missingContract.json();
    assert.equal(missingContract.status, 503);
    assert.equal(missingBody.error.code, "DEPLOYMENT_NOT_CONFIGURED");
    report.missingContract = {
      browserStatus: 503,
      browserRenderedCode: "DEPLOYMENT_NOT_CONFIGURED",
      separateActualEndpointStatus: missingContract.status,
      separateActualEndpointCode: missingBody.error.code,
    };
    let count = report.responses.length;
    await pause(2500);
    assert.equal(
      report.responses.length,
      count,
      "Unconfigured app repeated requests without a user action",
    );
    await batch([
      button("다시 확인"),
      ["wait", "--fn", "!document.querySelector('#main-task button')?.disabled"],
    ]);
    await poll(
      async () => report.responses.length,
      (n) => n === count + 1,
    );
    count = report.responses.length;
    await pause(2000);
    assert.equal(report.responses.length, count);
    await setLanguage("en");
    await batch([
      [
        "wait",
        "--fn",
        "document.querySelector('#main-task h2')?.textContent.includes('not configured yet')",
      ],
    ]);
    await screenshot("missing-config-en-desktop");
    await audit("missing-en-desktop");
    for (const language of ["en", "ko"]) {
      if (language === "ko") await setLanguage("ko");
      await batch([
        ["set", "viewport", "390", "844"],
        check("document.documentElement.scrollWidth<=innerWidth+1", "Mobile overflow"),
      ]);
      await screenshot(`missing-config-${language}-mobile`);
      await audit(`missing-${language}-mobile`);
    }
    assert(
      report.responses.every(
        (r) => r.status === 503 && (!r.code || r.code === "DEPLOYMENT_NOT_CONFIGURED"),
      ),
    );
    return {
      errors: "503 DEPLOYMENT_NOT_CONFIGURED only",
      manualRetryRequests: 1,
      idleAutomaticRetries: 0,
      locales: ["ko", "en"],
    };
  });
  await gate("old-page-manual-check-handoff-native-anchor-307-to-https-login", async () => {
    const old = page.url();
    await restart(true);
    assert.equal(page.url(), old, "Restart must preserve existing browser document");
    await batch([
      button("다시 확인"),
      ["wait", "--fn", "document.querySelector('#main-task a')?.textContent.includes('앱 열기')"],
      check(
        "document.querySelector('#main-task a')?.getAttribute('href')==='/'",
        "Handoff must be a native root navigation",
      ),
    ]);
    // The controller can abort its consumed request while entering offline.
    // CDP then exposes the HTTP status but cannot always retrieve that body.
    // Assert the actual browser-rendered code and independently read the real
    // configured endpoint; never substitute a mocked response for either.
    await batch([
      check(
        "document.querySelector('#main-task')?.textContent.includes('APP_HANDOFF_REQUIRED')",
        "Actual browser did not receive the handoff code",
      ),
    ]);
    const configured = report.responses.filter((r) => r.gate === activeGate);
    assert(configured.length > 0 && configured.every((r) => r.status === 503));
    const contract = await fetch(frontend + "/api/v1/auth/session", { redirect: "manual" });
    const contractBody = await contract.json();
    assert.equal(contract.status, 503);
    assert.equal(contractBody.error.code, "APP_HANDOFF_REQUIRED");
    report.configuredContract = {
      browserStatus: 503,
      browserRenderedCode: "APP_HANDOFF_REQUIRED",
      separateActualEndpointStatus: contract.status,
      separateActualEndpointCode: contractBody.error.code,
    };
    await screenshot("configured-old-page-handoff-mobile");
    await audit("configured-old-page-handoff");
    const requests = report.responses.length;
    await pause(2200);
    assert.equal(report.responses.length, requests, "Handoff repeated session fetches");
    await batch([
      ["click", "#main-task a"],
      [
        "wait",
        "--fn",
        `location.origin===${JSON.stringify(app.origin)} && !!document.querySelector('#local-password')`,
      ],
    ]);
    assert.equal(new URL(page.url()).origin, app.origin);
    await screenshot("https-app-login-mobile");
    await audit("https-login-mobile");
    assert(
      report.redirects.some(
        (r) => r.from === frontend + "/" && r.location === app.origin + "/" && r.navigation,
      ),
    );
    return {
      fullNavigation307: true,
      nativeAnchor: true,
      backendOrigin: app.origin,
      repeatedSessionRequests: 0,
    };
  });
  await gate("https-real-login-cookie-and-origin-isolation", async () => {
    await batch([
      ["fill", "#local-password", password],
      button("로그인"),
      ["wait", "--fn", "!!document.querySelector('#video-url')"],
    ]);
    const cookies = await context.cookies(app.origin);
    const auth = cookies.find((c) => c.httpOnly);
    assert(auth && auth.secure && auth.sameSite === "Lax");
    cookie = cookies.map((c) => `${c.name}=${c.value}`).join("; ");
    const sessionValue = await api("/auth/session");
    assert(sessionValue.authenticated);
    csrf = sessionValue.csrf_token;
    const settings = await api("/settings");
    assert(settings.capabilities.demo_data, "Refuse to create jobs outside test fixture");
    if (settings.language === "en") await setLanguage("ko");
    const foreign = await tls("/api/v1/settings", {
      method: "PATCH",
      headers: { Origin: "https://untrusted.example.org" },
      body: { language: "en" },
    });
    assert.equal(foreign.status, 403);
    const unauthenticated = await tls("/api/v1/jobs", { headers: { Cookie: "" } });
    assert.equal(unauthenticated.status, 401);
    const frontCookies = await context.cookies(frontend);
    assert.equal(frontCookies.length, 0, "Backend session cookie leaked to frontend origin");
    await screenshot("https-authenticated-mobile");
    await audit("https-authenticated-mobile");
    return {
      authenticated: true,
      secure: auth.secure,
      httpOnly: auth.httpOnly,
      sameSite: auth.sameSite,
      foreignOriginMutation: foreign.status,
      unauthenticatedJobs: unauthenticated.status,
      frontendCookies: 0,
    };
  });
  for (const mode of ["mp4", "mp3"])
    await gate(`https-fixture-${mode}-ui-worker-native-file-ffprobe`, async () => {
      await batch([["set", "viewport", "1280", "844"]]);
      await analyze(mode);
      const job = await createJob(mode);
      await verifyOutput(job);
      await verifyOutput(job, true);
      await screenshot(`https-${mode}-ready-desktop`);
      await audit(`https-${mode}-ready`);
      return {
        jobId: job.id,
        requestedKind: mode,
        actualKind: job.output.kind,
        bytes: job.artifact.bytes,
        nativeDownload: true,
      };
    });
  await gate("strict-console-and-preserved-personal-preview", async () => {
    const hostedGates = new Set([
      "owned-built-hosted-preview-and-pinned-local-tls",
      "missing-config-localized-desktop-mobile-accessible-manual-retry",
      "old-page-manual-check-handoff-native-anchor-307-to-https-login",
    ]);
    report.expectedConsoleErrors = report.consoleErrors.filter(
      (e) =>
        hostedGates.has(e.gate) &&
        /^Failed to load resource: the server responded with a status of 503/.test(e.message) &&
        e.location.url.startsWith(frontend + "/api/v1/auth/session"),
    );
    report.unexpectedConsoleErrors = report.consoleErrors.filter(
      (e) =>
        !report.expectedConsoleErrors.includes(e) &&
        !e.location.url.startsWith("https://grok.com/"),
    );
    assert.equal(
      report.unexpectedConsoleErrors.length,
      0,
      JSON.stringify(report.unexpectedConsoleErrors),
    );
    assert.equal(report.pageErrors.length, 0);
    const after = await personalSnapshot();
    assert.deepEqual(after.operator, before.operator);
    assert.equal(after.jobs, before.jobs);
    assert.deepEqual(
      after.runners,
      before.runners,
      "Personal preview processes must not be restarted by hosted QA",
    );
    assert(
      after.api &&
        after.web &&
        after.worker === "ready" &&
        Object.values(after.owned).every(Boolean),
    );
    report.personalPreview = {
      operatorMetadataUnchanged: true,
      jobsCountUnchanged: true,
      allRunnersOwned: true,
      personalProcessesUnchanged: true,
      apiAndWebHealthy: true,
      exclusiveWorkerHeartbeat: "ready",
    };
    return report.personalPreview;
  });
  report.ok = true;
} catch (error) {
  report.ok = false;
  report.error = String(error.stack || error).replaceAll(password, "[redacted]");
  console.error(report.error);
  if (page)
    try {
      await screenshot("failure");
    } catch {
      /* diagnostic only */
    }
  process.exitCode = 1;
} finally {
  try {
    if (browser) await browser.close();
  } catch {
    /* process cleanup follows */
  }
  if (chrome) chrome.kill("SIGTERM");
  if (qaStarted) {
    let stopError;
    try {
      await exec("npm", ["run", "preview:stop"], { cwd: root, env, timeout: 20000 });
    } catch (error) {
      stopError = String(error.message).replaceAll(password, "[redacted]");
    }
    const closed = !(await portOpen(8081));
    report.cleanup = { qa8081Closed: closed, stopCommandLimitation: stopError || null };
    if (closed) {
      try {
        const pid = Number((await readFile(join(root, ".grok/preview.pid"), "utf8")).trim());
        const state = (await readFile(`/proc/${pid}/stat`, "utf8"))
          .split(")")
          .at(-1)
          .trim()
          .split(/\s+/)[0];
        if (state === "Z") await unlink(join(root, ".grok/preview.pid"));
      } catch {
        /* no stale marker or exited */
      }
    } else {
      report.ok = false;
      process.exitCode = 1;
    }
  }
  report.finishedAt = new Date().toISOString();
  await writeFile(join(output, "verification.json"), JSON.stringify(report, null, 2) + "\n");
  console.log(JSON.stringify({ ok: report.ok, report: join(output, "verification.json") }));
}
