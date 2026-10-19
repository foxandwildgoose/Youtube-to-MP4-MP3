import {
  isAnalysis,
  isJob,
  isJobsPage,
  isPlaylist,
  isReadiness,
  isSession,
  isSettings,
} from "./contracts.ts";
import type {
  Analysis,
  Job,
  JobRequest,
  JobsPage,
  JobsQuery,
  PlaylistInspection,
  Readiness,
  Settings,
} from "./contracts.ts";
export type * from "./contracts.ts";

export type RequestContext = { method: string; path: string };
export class ApiError extends Error {
  readonly status: number | null;
  readonly code: string;
  readonly action: string;
  readonly retryable: boolean;
  readonly retryAfterSeconds: number | null;
  readonly retryAt: number | null;
  readonly context: RequestContext;
  readonly uncertain: boolean;
  constructor(options: {
    status?: number | null;
    code: string;
    message?: string;
    action?: string;
    retryable?: boolean;
    retryAfterSeconds?: number | null;
    context?: RequestContext;
    uncertain?: boolean;
  }) {
    super(options.message || options.code);
    this.name = "ApiError";
    this.status = options.status ?? null;
    this.code = options.code;
    this.action = options.action || "retry";
    this.retryable = options.retryable ?? false;
    this.retryAfterSeconds = options.retryAfterSeconds ?? null;
    this.retryAt =
      this.retryAfterSeconds === null ? null : Date.now() + this.retryAfterSeconds * 1000;
    this.context = options.context || { method: "GET", path: "" };
    this.uncertain = options.uncertain ?? false;
  }
}
export function asApiError(error: unknown): ApiError {
  return error instanceof ApiError
    ? error
    : new ApiError({ code: "UNEXPECTED_ERROR", retryable: true });
}
export type RequestOptions = { signal?: AbortSignal; timeoutMs?: number; retries?: number };
type Validator<T> = (value: unknown) => value is T;
const MAX_RESPONSE_BYTES = 2 * 1024 * 1024;
function object(value: unknown): value is Record<string, unknown> {
  return typeof value === "object" && value !== null && !Array.isArray(value);
}
function retryAfter(response: Response, body: unknown): number | null {
  const header = response.headers.get("Retry-After");
  const bodyValue = object(body) && object(body.error) ? body.error.retry_after_seconds : null;
  const seconds =
    header && /^\d+(\.\d+)?$/.test(header.trim())
      ? Number(header)
      : header && Number.isFinite(Date.parse(header))
        ? Math.max(0, (Date.parse(header) - Date.now()) / 1000)
        : bodyValue;
  return typeof seconds === "number" && Number.isFinite(seconds) && seconds >= 0
    ? Math.ceil(Math.min(seconds, 86400 * 7))
    : null;
}
async function boundedText(response: Response): Promise<string> {
  if (Number(response.headers.get("Content-Length")) > MAX_RESPONSE_BYTES) {
    await response.body?.cancel();
    throw new ApiError({ code: "RESPONSE_TOO_LARGE", status: response.status });
  }
  if (!response.body) return "";
  const reader = response.body.getReader();
  const decoder = new TextDecoder();
  let size = 0;
  let result = "";
  try {
    while (true) {
      const { done, value } = await reader.read();
      if (done) break;
      size += value.byteLength;
      if (size > MAX_RESPONSE_BYTES) {
        await reader.cancel();
        throw new ApiError({ code: "RESPONSE_TOO_LARGE", status: response.status });
      }
      result += decoder.decode(value, { stream: true });
    }
    return result + decoder.decode();
  } finally {
    reader.releaseLock();
  }
}
function authHeaders(csrf?: string, locale?: string): Record<string, string> {
  return {
    "Content-Type": "application/json",
    "X-Requested-With": "seorap",
    ...(csrf ? { "X-CSRF-Token": csrf } : {}),
    ...(locale ? { "X-Locale": locale } : {}),
  };
}
async function once<T>(
  path: string,
  init: RequestInit,
  validate: Validator<T> | undefined,
  options: RequestOptions,
): Promise<T> {
  const context = { method: init.method || "GET", path: path.split("?")[0] };
  const controller = new AbortController();
  const abort = () => controller.abort(options.signal?.reason);
  options.signal?.addEventListener("abort", abort, { once: true });
  if (options.signal?.aborted) abort();
  let timedOut = false;
  const timeout = setTimeout(() => {
    timedOut = true;
    controller.abort();
  }, options.timeoutMs ?? 15000);
  try {
    const response = await fetch(path, {
      ...init,
      signal: controller.signal,
      credentials: "same-origin",
      cache: "no-store",
    });
    const content = context.method === "HEAD" ? "" : await boundedText(response);
    let body: unknown;
    let malformed = false;
    if (content.trim()) {
      try {
        body = JSON.parse(content);
      } catch {
        malformed = true;
      }
    }
    if (!response.ok) {
      const detail = object(body) && object(body.error) ? body.error : null;
      throw new ApiError({
        status: response.status,
        code: typeof detail?.code === "string" ? detail.code : `HTTP_${response.status}`,
        message: typeof detail?.message === "string" ? detail.message.slice(0, 1000) : undefined,
        action: typeof detail?.action === "string" ? detail.action.slice(0, 1000) : "retry",
        retryable:
          typeof detail?.retryable === "boolean"
            ? detail.retryable
            : response.status >= 500 || response.status === 429,
        retryAfterSeconds: retryAfter(response, body),
        context,
        uncertain: !["GET", "HEAD"].includes(context.method) && response.status >= 500,
      });
    }
    if (context.method === "HEAD" || response.status === 204 || (!validate && !content.trim()))
      return undefined as T;
    if (malformed || !content.trim() || (validate && !validate(body))) {
      throw new ApiError({
        status: response.status,
        code: "INVALID_RESPONSE",
        retryable: true,
        context,
        uncertain: !["GET", "HEAD"].includes(context.method),
      });
    }
    return body as T;
  } catch (error) {
    if (error instanceof ApiError) {
      if (!error.context.path)
        throw new ApiError({
          ...error,
          message: error.message,
          context,
          uncertain:
            error.uncertain ||
            (!["GET", "HEAD"].includes(context.method) && error.code === "RESPONSE_TOO_LARGE"),
        });
      throw error;
    }
    throw new ApiError({
      code: timedOut ? "TIMEOUT" : options.signal?.aborted ? "ABORTED" : "NETWORK_ERROR",
      retryable: !options.signal?.aborted,
      context,
      uncertain: !["GET", "HEAD"].includes(context.method),
    });
  } finally {
    clearTimeout(timeout);
    options.signal?.removeEventListener("abort", abort);
  }
}
/** Only safe reads retry automatically. Creates replay explicitly with their original intent key. */
export async function requestJson<T>(
  path: string,
  init: RequestInit = {},
  validate?: Validator<T>,
  options: RequestOptions = {},
): Promise<T> {
  const attempts = ["GET", "HEAD"].includes(init.method || "GET")
    ? Math.max(0, Math.min(options.retries ?? 1, 1))
    : 0;
  for (let attempt = 0; ; attempt += 1) {
    try {
      return await once(path, init, validate, options);
    } catch (error) {
      if (
        !(error instanceof ApiError) ||
        attempt >= attempts ||
        !error.retryable ||
        error.code === "ABORTED" ||
        error.retryAfterSeconds !== null ||
        (error.status !== null && ![502, 503, 504].includes(error.status))
      )
        throw error;
    }
  }
}
const idPath = (id: string) => `/api/v1/jobs/${encodeURIComponent(id)}`;
export const api = {
  health: (options?: RequestOptions) =>
    requestJson("/healthz", {}, undefined, options)
      .then(() => true)
      .catch(() => false),
  session: (options?: RequestOptions) =>
    requestJson("/api/v1/auth/session", {}, isSession, options),
  bootstrap: (password: string, options?: RequestOptions) =>
    requestJson(
      "/api/v1/auth/bootstrap",
      { method: "POST", headers: authHeaders(), body: JSON.stringify({ password }) },
      undefined,
      options,
    ),
  login: (password: string, options?: RequestOptions) =>
    requestJson(
      "/api/v1/auth/login",
      { method: "POST", headers: authHeaders(), body: JSON.stringify({ password }) },
      isSession,
      options,
    ),
  logout: (csrf: string, options?: RequestOptions) =>
    requestJson(
      "/api/v1/auth/logout",
      { method: "POST", headers: authHeaders(csrf) },
      undefined,
      options,
    ),
  analyze: (
    url: string,
    csrf: string,
    locale: string,
    options?: RequestOptions,
  ): Promise<Analysis> =>
    requestJson(
      "/api/v1/analyses",
      { method: "POST", headers: authHeaders(csrf, locale), body: JSON.stringify({ url }) },
      isAnalysis,
      { timeoutMs: 70000, ...options },
    ),
  settings: (csrf: string, options?: RequestOptions): Promise<Settings> =>
    requestJson("/api/v1/settings", { headers: authHeaders(csrf) }, isSettings, options),
  readiness: (csrf: string, options?: RequestOptions): Promise<Readiness> =>
    requestJson("/api/v1/readiness", { headers: authHeaders(csrf) }, isReadiness, options),
  patchSettings: (
    csrf: string,
    body: Partial<Pick<Settings, "language" | "theme" | "mp3_bitrate">>,
    options?: RequestOptions,
  ): Promise<Settings> =>
    requestJson(
      "/api/v1/settings",
      { method: "PATCH", headers: authHeaders(csrf), body: JSON.stringify(body) },
      isSettings,
      options,
    ),
  createJob: (
    csrf: string,
    locale: string,
    key: string,
    body: JobRequest,
    options?: RequestOptions,
  ): Promise<Job> =>
    requestJson(
      "/api/v1/jobs",
      {
        method: "POST",
        headers: { ...authHeaders(csrf, locale), "Idempotency-Key": key },
        body: JSON.stringify(body),
      },
      isJob,
      options,
    ),
  retryJob: (
    csrf: string,
    locale: string,
    parentId: string,
    key: string,
    body: JobRequest,
    options?: RequestOptions,
  ): Promise<Job> =>
    requestJson(
      `${idPath(parentId)}/retry`,
      {
        method: "POST",
        headers: { ...authHeaders(csrf, locale), "Idempotency-Key": key },
        body: JSON.stringify(body),
      },
      isJob,
      options,
    ),
  playlist: (
    csrf: string,
    locale: string,
    url: string,
    options?: RequestOptions,
  ): Promise<PlaylistInspection> =>
    requestJson(
      "/api/v1/playlists/analyze",
      { method: "POST", headers: authHeaders(csrf, locale), body: JSON.stringify({ url }) },
      isPlaylist,
      { timeoutMs: 70000, ...options },
    ),
  jobs: (csrf: string, query: JobsQuery = {}, options?: RequestOptions): Promise<JobsPage> => {
    const params = new URLSearchParams({ limit: "30" });
    for (const [key, value] of Object.entries(query))
      if (value !== undefined && value !== "") params.set(key, String(value));
    return requestJson(
      `/api/v1/jobs?${params}`,
      { headers: authHeaders(csrf) },
      isJobsPage,
      options,
    );
  },
  job: (csrf: string, id: string, options?: RequestOptions): Promise<Job> =>
    requestJson(idPath(id), { headers: authHeaders(csrf) }, isJob, options),
  cancel: (csrf: string, id: string, options?: RequestOptions): Promise<Job> =>
    requestJson(
      `${idPath(id)}/cancel`,
      { method: "POST", headers: authHeaders(csrf) },
      isJob,
      options,
    ),
  retention: (csrf: string, id: string, keep: boolean, options?: RequestOptions): Promise<Job> =>
    requestJson(
      `${idPath(id)}/retention`,
      {
        method: "PATCH",
        headers: authHeaders(csrf),
        body: JSON.stringify({ keep_on_server: keep }),
      },
      isJob,
      options,
    ),
  deleteFile: (csrf: string, id: string, options?: RequestOptions): Promise<Job> =>
    requestJson(
      `${idPath(id)}/file`,
      { method: "DELETE", headers: authHeaders(csrf) },
      isJob,
      options,
    ),
  deleteHistory: (csrf: string, id: string, options?: RequestOptions): Promise<void> =>
    requestJson(idPath(id), { method: "DELETE", headers: authHeaders(csrf) }, undefined, options),
  checkFile: async (csrf: string, id: string, options?: RequestOptions): Promise<void> => {
    try {
      await requestJson<void>(
        `${idPath(id)}/file`,
        { method: "HEAD", headers: authHeaders(csrf) },
        undefined,
        options,
      );
    } catch (error) {
      if (error instanceof ApiError && [404, 410].includes(error.status || 0))
        throw new ApiError({
          ...error,
          code: error.status === 410 ? "FILE_EXPIRED" : "FILE_MISSING",
          action: "reanalyze",
        });
      throw error;
    }
  },
  diagnostics: (csrf: string, options?: RequestOptions): Promise<Record<string, unknown>> =>
    requestJson(
      "/api/v1/diagnostics",
      { headers: authHeaders(csrf) },
      (value): value is Record<string, unknown> => object(value),
      options,
    ),
};
