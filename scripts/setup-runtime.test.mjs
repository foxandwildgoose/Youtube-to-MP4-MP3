import { test } from 'node:test';
import assert from 'node:assert/strict';
import { mkdtempSync, mkdirSync, copyFileSync, writeFileSync, readFileSync, existsSync, rmSync } from 'node:fs';
import { tmpdir } from 'node:os';
import { join, resolve } from 'node:path';
import { spawnSync } from 'node:child_process';

const root = resolve(import.meta.dirname, '..');
function folder(t, template = true) {
  const dir = mkdtempSync(join(tmpdir(), 'seorap-setup-'));
  t.after(() => rmSync(dir, { recursive: true, force: true }));
  mkdirSync(join(dir, 'scripts'));
  mkdirSync(join(dir, 'stub'));
  for (const file of ['setup.sh', 'setup.ps1', 'install-deno.sh']) copyFileSync(join(root, 'scripts', file), join(dir, 'scripts', file));
  for (const file of ['docker-compose.yml', 'docker-compose.override.yml', 'docker-compose.cloud.yml']) copyFileSync(join(root, file), join(dir, file));
  if (template) copyFileSync(join(root, '.env.example'), join(dir, '.env.example'));
  const docker = `#!/bin/sh\nprintf '%s\\n' "$*" >> "$FAKE_DOCKER_LOG"\ncase "$*" in *"$FAKE_DOCKER_FAIL"*) if [ -n "$FAKE_DOCKER_FAIL" ]; then exit 42; fi ;; esac\nexit 0\n`;
  writeFileSync(join(dir, 'stub', 'docker'), docker, { mode: 0o755 });
  return dir;
}
function run(dir, fail = '', command = 'sh', script = 'setup.sh', extraEnv = {}) {
  return spawnSync(command, [join(dir, 'scripts', script)], {
    encoding: 'utf8', env: { ...process.env, CODEX_PROXY_CERT: '', PATH: `${join(dir, 'stub')}:${process.env.PATH}`, FAKE_DOCKER_LOG: join(dir, 'calls'), FAKE_DOCKER_FAIL: fail, ...extraEnv },
  });
}
function calls(dir) { return existsSync(join(dir, 'calls')) ? readFileSync(join(dir, 'calls'), 'utf8') : ''; }

test('V01 clean setup creates personal template, applies local override and waits for both services', t => {
  const dir = folder(t);
  const result = run(dir);
  assert.equal(result.status, 0, result.stderr);
  assert.equal(readFileSync(join(dir, '.env'), 'utf8'), readFileSync(join(root, '.env.example'), 'utf8'));
  assert.match(calls(dir), /compose version\ninfo\ncompose -f docker-compose.yml -f docker-compose.override.yml config --quiet\ncompose -f docker-compose.yml -f docker-compose.override.yml build\ncompose -f docker-compose.yml -f docker-compose.override.yml up -d --wait --wait-timeout 90\n/);
  assert.match(result.stdout, /Ready:/);
  assert.match(result.stdout, /No login password is needed/);
  assert.doesNotMatch(result.stdout, /Initialize the password|app\.cli bootstrap/);
});
test('V01 existing operator environment remains byte-identical', t => {
  const dir = folder(t);
  writeFileSync(join(dir, '.env'), 'REQUIRE_PASSWORD=1\n# operator custom file\n');
  const result = run(dir);
  assert.equal(result.status, 0);
  assert.equal(readFileSync(join(dir, '.env'), 'utf8'), 'REQUIRE_PASSWORD=1\n# operator custom file\n');
  assert.match(calls(dir), /-f docker-compose.override.yml up/);
  assert.doesNotMatch(result.stdout, /Initialize the password|app\.cli bootstrap/);
});
test('V01 managed-cloud setup includes personal override before proxy trust overlay', t => {
  const dir = folder(t);
  const result = run(dir, '', 'sh', 'setup.sh', { CODEX_PROXY_CERT: '/provided/public-ca.pem' });
  assert.equal(result.status, 0, result.stderr);
  assert.match(calls(dir), /-f docker-compose.yml -f docker-compose.override.yml -f docker-compose.cloud.yml up -d --wait/);
  assert.doesNotMatch(result.stdout, /Initialize the password|app\.cli bootstrap/);
});
test('V01 actual Compose config applies passwordless loopback defaults over an older protected env', { skip: spawnSync('docker', ['compose', 'version']).status !== 0 ? 'Docker Compose CLI is unavailable; config boundary must run on a Docker host.' : false }, t => {
  const dir = folder(t);
  for (const file of ['docker-compose.fixture.yml', 'docker-compose.https.yml']) copyFileSync(join(root, file), join(dir, file));
  const existing = `${readFileSync(join(root, '.env.example'), 'utf8').replace('REQUIRE_PASSWORD=0', 'REQUIRE_PASSWORD=1')}\n# preserve operator settings\n`;
  writeFileSync(join(dir, '.env'), existing);
  const env = { ...process.env, SEORAP_PUBLIC_HOST: 'downloads.example.com', SEORAP_FIXTURE_DIR: dir };
  delete env.COMPOSE_FILE;
  function config(files = []) {
    const args = ['compose', '--project-directory', dir, ...files.flatMap(file => ['-f', join(dir, file)]), 'config', '--format', 'json'];
    const result = spawnSync('docker', args, { encoding: 'utf8', env, cwd: dir });
    assert.equal(result.status, 0, result.stderr);
    return JSON.parse(result.stdout);
  }
  for (const personal of [config(), config(['docker-compose.yml', 'docker-compose.override.yml'])]) {
    for (const service of ['app', 'worker']) {
      const settings = personal.services[service].environment;
      assert.equal(settings.REQUIRE_PASSWORD, '0');
      assert.equal(settings.LOCAL_HTTP, '1');
      assert.equal(settings.ALLOW_HTTP_BOOTSTRAP, '0');
      assert.equal(settings.ALLOWED_HOSTS, '127.0.0.1,localhost');
    }
    assert.equal(personal.services.app.ports.length, 1);
    assert.equal(personal.services.app.ports[0].host_ip, '127.0.0.1');
    assert.equal(personal.services.app.ports[0].published, '8000');
    assert.equal(personal.services.app.volumes[0].source, 'seorap-data');
  }
  for (const overlay of ['docker-compose.fixture.yml', 'docker-compose.https.yml']) {
    const protectedConfig = config(['docker-compose.yml', overlay]);
    for (const service of ['app', 'worker']) assert.equal(protectedConfig.services[service].environment.REQUIRE_PASSWORD, '1');
    if (overlay.includes('https')) assert.deepEqual(protectedConfig.services.app.ports ?? [], []);
  }
  assert.equal(readFileSync(join(dir, '.env'), 'utf8'), existing);
});
test('V01 missing template fails clearly before build', t => {
  const dir = folder(t, false);
  const result = run(dir);
  assert.notEqual(result.status, 0);
  assert.match(result.stderr, /Missing \.env.example/);
  assert.doesNotMatch(calls(dir), /build|up -d/);
});
for (const failure of ['compose version', 'info', 'config --quiet', 'build', 'up -d']) {
  test(`V01 setup propagates ${failure} failure and prints no success`, t => {
    const dir = folder(t);
    const result = run(dir, failure);
    assert.notEqual(result.status, 0);
    assert.doesNotMatch(result.stdout, /Ready:|Initialize the password/);
    if (failure !== 'up -d') assert.doesNotMatch(calls(dir), /up -d/);
  });
}
test('I09 PowerShell native failure harness', { skip: spawnSync('pwsh', ['-NoProfile', '-Command', 'exit 0']).status !== 0 ? 'PowerShell is not installed; Windows 5.1/7 execution remains an external verification gate.' : false }, t => {
  for (const failure of ['build', 'up -d']) {
    const dir = folder(t);
    const result = run(dir, failure, 'pwsh', 'setup.ps1');
    assert.notEqual(result.status, 0);
    assert.doesNotMatch(result.stdout, /Ready:|Initialize the password/);
    if (failure === 'build') assert.doesNotMatch(calls(dir), /up -d/);
  }
});
test('I08 unsupported native architecture fails before download', t => {
  const dir = folder(t);
  const result = spawnSync('sh', [join(dir, 'scripts/install-deno.sh'), join(dir, 'bin')], { encoding: 'utf8', env: { ...process.env, TARGETARCH: 'arm64' } });
  assert.equal(result.status, 2);
  assert.match(result.stderr, /supports linux\/amd64/);
  assert.equal(existsSync(join(dir, 'bin')), false);
});
test('I08 corrupt Deno archive never replaces an existing executable', t => {
  const dir = folder(t);
  mkdirSync(join(dir, 'bin'));
  writeFileSync(join(dir, 'bin/deno'), 'keep verified tool');
  writeFileSync(join(dir, 'stub/curl'), '#!/bin/sh\nwhile [ "$#" -gt 0 ]; do if [ "$1" = "--output" ]; then shift; printf corrupted > "$1"; exit 0; fi; shift; done\nexit 1\n', { mode: 0o755 });
  const result = spawnSync('sh', [join(dir, 'scripts/install-deno.sh'), join(dir, 'bin')], { encoding: 'utf8', env: { ...process.env, TARGETARCH: 'amd64', PATH: `${join(dir, 'stub')}:${process.env.PATH}` } });
  assert.notEqual(result.status, 0);
  assert.equal(readFileSync(join(dir, 'bin/deno'), 'utf8'), 'keep verified tool');
});
