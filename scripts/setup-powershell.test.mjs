import { test } from 'node:test';
import assert from 'node:assert/strict';
import { mkdtempSync, mkdirSync, copyFileSync, writeFileSync, readFileSync, existsSync, rmSync } from 'node:fs';
import { tmpdir } from 'node:os';
import { join, resolve } from 'node:path';
import { spawnSync } from 'node:child_process';

const available = ['powershell', 'pwsh'].filter(shell => spawnSync(shell, ['-NoProfile', '-Command', 'exit 0']).status === 0);
const root = resolve(import.meta.dirname, '..');
// Native .cmd stubs exercise LASTEXITCODE under Windows PowerShell 5.1 and 7.
for (const shell of available) {
  test(`I09 ${shell} setup success, preservation and native failures`, { skip: process.platform !== 'win32' ? 'Windows-native .cmd harness requires Windows.' : false }, t => {
    for (const failure of ['', 'existing', 'compose version', 'info', 'config', 'build', 'up']) {
      const dir = mkdtempSync(join(tmpdir(), 'seorap-ps-'));
      t.after(() => rmSync(dir, { recursive: true, force: true }));
      mkdirSync(join(dir, 'scripts'));
      mkdirSync(join(dir, 'stub'));
      copyFileSync(join(root, 'scripts/setup.ps1'), join(dir, 'scripts/setup.ps1'));
      copyFileSync(join(root, '.env.example'), join(dir, '.env.example'));
      for (const file of ['docker-compose.yml', 'docker-compose.override.yml']) copyFileSync(join(root, file), join(dir, file));
      writeFileSync(join(dir, 'stub/docker.cmd'), '@echo off\r\necho %*>>"%FAKE_DOCKER_LOG%"\r\nif not "%FAKE_DOCKER_FAIL%"=="" (echo %*| findstr /c:"%FAKE_DOCKER_FAIL%" >nul && exit /b 42)\r\nexit /b 0\r\n');
      if (failure) writeFileSync(join(dir, '.env'), '# preserve existing settings\nREQUIRE_PASSWORD=1\n');
      const result = spawnSync(shell, ['-NoProfile', '-ExecutionPolicy', 'Bypass', '-File', join(dir, 'scripts/setup.ps1')], {
        encoding: 'utf8', env: { ...process.env, PATH: `${join(dir, 'stub')};${process.env.PATH}`, FAKE_DOCKER_LOG: join(dir, 'calls'), FAKE_DOCKER_FAIL: failure === 'existing' ? '' : failure },
      });
      const calls = existsSync(join(dir, 'calls')) ? readFileSync(join(dir, 'calls'), 'utf8') : '';
      if (failure && failure !== 'existing') {
        assert.notEqual(result.status, 0, `${shell} ${failure}: ${result.stdout} ${result.stderr}`);
        assert.doesNotMatch(result.stdout, /Ready:|Initialize the password/);
        if (failure !== 'up') assert.doesNotMatch(calls, /up -d/);
        assert.equal(readFileSync(join(dir, '.env'), 'utf8'), '# preserve existing settings\nREQUIRE_PASSWORD=1\n');
      } else {
        assert.equal(result.status, 0, result.stderr);
        assert.match(calls, /up -d --wait --wait-timeout 90/);
        assert.match(result.stdout, /No login password is needed/);
        assert.doesNotMatch(result.stdout, /Initialize the password|app\.cli bootstrap/);
        assert.equal(readFileSync(join(dir, '.env'), 'utf8'), failure === 'existing' ? '# preserve existing settings\nREQUIRE_PASSWORD=1\n' : readFileSync(join(root, '.env.example'), 'utf8'));
      }
    }
  });
}
if (!available.length) test('I09 Windows PowerShell 5.1/7 runtime', { skip: 'PowerShell is not installed; CI Windows matrix runs native .cmd stubs.' }, () => {});
