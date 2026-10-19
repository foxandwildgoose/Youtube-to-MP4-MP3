import test from 'node:test';
import assert from 'node:assert/strict';
import { BODY_LIMIT, boundedBody, previewAllowed } from './seorap-preview-policy.ts';
const req = (origin: string, host = '127.0.0.1:8080') => new Request('http://' + host + '/api/v1/jobs', { method: 'POST', headers: { host, origin }, body: '{}' });
test('incoming origin and host checked before trusted rewrite', () => {
  assert.equal(previewAllowed(req('http://127.0.0.1:8080')), true);
  assert.equal(previewAllowed(req('https://evil.example')), false);
  assert.equal(previewAllowed(req('http://127.0.0.1:8080','evil.example')), false);
  assert.equal(previewAllowed(req('https://preview.example','preview.example'), 'preview.example', 'https://preview.example'), true);
});
test('declared and actual streamed byte caps stop before oversized body completes', async () => {
  assert.deepEqual(await boundedBody(req('http://127.0.0.1:8080')), new TextEncoder().encode('{}'));
  await assert.rejects(boundedBody(new Request('http://localhost', { method:'POST', headers:{'content-length':String(BODY_LIMIT+1)}, body:'x' })), (r: unknown) => r instanceof Response && r.status === 413);
  let pulled=0, cancelled=false;
  const body=new ReadableStream({pull(c){pulled++;c.enqueue(new Uint8Array(17000));if(pulled===20)c.close()},cancel(){cancelled=true}});
  await assert.rejects(boundedBody(new Request('http://localhost', {method:'POST',body,duplex:'half'} as RequestInit)), (r: unknown)=>r instanceof Response && r.status===413);
  assert.ok(pulled<20);assert.ok(cancelled);
});
