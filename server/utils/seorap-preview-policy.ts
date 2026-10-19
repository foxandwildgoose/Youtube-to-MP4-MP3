/** Explicit Grok development forwarding boundary, evaluated before translation. */
export const BODY_LIMIT = 65536;
const MUTATING = new Set(['POST', 'PUT', 'PATCH', 'DELETE']);

export function previewAllowed(request: Request, extraHosts = process.env.SEORAP_PREVIEW_ALLOWED_HOSTS || '', extraOrigins = process.env.SEORAP_PREVIEW_ORIGINS || ''): boolean {
  const hosts = new Set(['localhost:8080', '127.0.0.1:8080', 'localhost:8081', '127.0.0.1:8081', ...extraHosts.split(',').map(v => v.trim()).filter(Boolean)]);
  const origins = new Set(['http://localhost:8080', 'http://127.0.0.1:8080', 'http://localhost:8081', 'http://127.0.0.1:8081', ...extraOrigins.split(',').map(v => v.trim()).filter(Boolean)]);
  const host = request.headers.get('host') || new URL(request.url).host;
  if (!hosts.has(host) || request.headers.get('sec-fetch-site') === 'cross-site') return false;
  const origin = request.headers.get('origin');
  if (MUTATING.has(request.method) && !origin) return false;
  if (origin && !origins.has(origin)) return false;
  return true;
}

export function proxyError(status: number, code: string): Response {
  const ko = code === 'CSRF_FAILED' ? '허용되지 않은 요청 출처입니다.' : code === 'LIMIT_EXCEEDED' ? '요청 크기 한도를 넘었습니다.' : '처리 서비스에 연결할 수 없습니다.';
  return Response.json({ error: { code, message: ko, action: '요청 출처와 로컬 처리 서비스 상태를 확인하세요.', retryable: status >= 500 } }, { status });
}

export async function boundedBody(request: Request): Promise<Uint8Array | null> {
  const length = request.headers.get('content-length');
  if (length !== null && (!/^\d+$/.test(length) || Number(length) > BODY_LIMIT)) throw proxyError(413, 'LIMIT_EXCEEDED');
  if (!request.body) return null;
  const reader = request.body.getReader();
  const chunks: Uint8Array[] = [];
  let size = 0;
  try {
    while (true) {
      const result = await reader.read();
      if (result.done) break;
      size += result.value.byteLength;
      if (size > BODY_LIMIT) throw proxyError(413, 'LIMIT_EXCEEDED');
      chunks.push(result.value);
    }
  } catch (error) {
    await reader.cancel().catch(() => undefined);
    throw error;
  } finally {
    reader.releaseLock();
  }
  const body = new Uint8Array(size);
  let offset = 0;
  for (const chunk of chunks) { body.set(chunk, offset); offset += chunk.byteLength; }
  return body;
}
