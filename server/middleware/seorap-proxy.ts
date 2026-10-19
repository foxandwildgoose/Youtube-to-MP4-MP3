/** Development Grok bridge. Personal Compose serves the SPA directly. */
import { boundedBody, previewAllowed, proxyError } from '../utils/seorap-preview-policy.ts';
interface ProxyEvent { url: URL; req: Request }
const TARGET = 'http://127.0.0.1:8000';

export default async function seorapProxy(event: ProxyEvent, next: () => unknown | Promise<unknown>): Promise<unknown> {
  const path = event.url.pathname;
  if (path !== '/healthz' && !path.startsWith('/api/')) return next();
  const incoming = event.req;
  if (!previewAllowed(incoming)) return proxyError(403, 'CSRF_FAILED');
  const method = incoming.method.toUpperCase();
  const headers = new Headers(incoming.headers);
  // Only the explicit validated development origins are translated.
  headers.set('host', '127.0.0.1:8000');
  if (headers.has('origin')) headers.set('origin', TARGET);
  headers.delete('content-length');
  headers.delete('x-forwarded-host');
  headers.delete('x-forwarded-proto');
  let timer: ReturnType<typeof setTimeout> | undefined;
  const controller = new AbortController();
  const onAbort = () => controller.abort();
  incoming.signal.addEventListener('abort', onAbort, { once: true });
  try {
    // File and event streams have their own lifecycle; mutation/probes are bounded.
    if (method !== 'GET' && method !== 'HEAD') timer = setTimeout(() => controller.abort(), 70000);
    const body = method === 'GET' || method === 'HEAD' ? null : await boundedBody(incoming);
    const response = await fetch(TARGET + path + event.url.search, {
      method, headers, redirect: 'manual', signal: controller.signal,
      ...(body ? { body: body as BodyInit } : {}),
    });
    const out = new Headers();
    response.headers.forEach((value, key) => {
      if (key.toLowerCase() !== 'set-cookie') out.set(key, value);
    });
    for (const cookie of response.headers.getSetCookie()) out.append('set-cookie', cookie);
    // fetch transparently decodes compression; never forward stale byte metadata.
    if (out.has('content-encoding')) { out.delete('content-encoding'); out.delete('content-length'); }
    return new Response(response.body, { status: response.status, headers: out });
  } catch (error) {
    if (error instanceof Response) return error;
    return proxyError(503, 'WORKER_UNAVAILABLE');
  } finally {
    if (timer) clearTimeout(timer);
    // Keep abort forwarding for the lifetime of a streamed response.
  }
}
