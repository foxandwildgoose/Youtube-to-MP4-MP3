export type ErrorBody = {
  error: {
    code: string;
    message: string;
    retryable: boolean;
    action: string;
    retry_after_seconds?: number;
  };
};

export type Choice = {
  choice_id: string;
  kind: "mp4" | "mp3" | "original_audio";
  label: string;
  conversion_required: boolean;
  requires_consent: boolean;
  width: number | null;
  height: number | null;
  fps: number | null;
  vcodec: string | null;
  acodec: string | null;
  audio_language: string | null;
  audio_role: string | null;
  container: string;
  estimated_bytes: number | null;
  size_is_estimate: boolean;
  resolution_label: string | null;
  portrait: boolean;
  bitrate_kbps: number | null;
  is_default: boolean;
};

export type Analysis = {
  analysis_id: string;
  expires_at: string;
  source: {
    video_id: string;
    canonical_url: string;
    title: string;
    channel: string;
    duration_seconds: number | null;
    thumbnail_url: string | null;
    live_status: string | null;
    ignored_timestamp: boolean;
    ignored_playlist: boolean;
  };
  audio_tracks: { language: string | null; role: string; codec: string }[];
  choices: Choice[];
};

export type Job = {
  id: string;
  revision: number;
  status: "queued" | "running" | "succeeded" | "failed" | "cancelled" | "interrupted";
  phase: string | null;
  cancel_requested: boolean;
  queue_position: number | null;
  file_state: "none" | "available" | "expired" | "deleted" | "missing";
  keep_on_server: boolean;
  progress: {
    downloaded_bytes: number | null;
    total_bytes: number | null;
    total_is_estimate: boolean;
    speed_bps: number | null;
    eta_seconds: number | null;
    percent: number | null;
    phase?: string;
  } | null;
  error: ErrorBody["error"] | null;
  source: { title?: string; channel?: string; canonical_url?: string; video_id?: string; duration_seconds?: number | null };
  output: { kind: string; label: string; container: string; conversion_required: boolean };
  artifact: { bytes: number; filename: string; mime: string; expires_at: string | null } | null;
  created_at: string;
  updated_at: string;
};

export type Session =
  | { authenticated: false; bootstrapped: boolean; password_required?: boolean }
  | {
      authenticated: true;
      bootstrapped: true;
      csrf_token: string;
      expires_at: string;
      language: "ko" | "en";
      theme: string;
      password_required?: boolean;
    };

export type PlaylistInspection = {
  playlist_id: string;
  canonical_url: string;
  limit: number;
  limited: boolean;
  stopped_at_cap: boolean;
  entries: {
    position: number;
    video_id: string | null;
    title: string | null;
    available: boolean;
    reason: string | null;
    canonical_url: string | null;
  }[];
};
export type Settings = {
  language: "ko" | "en";
  theme: "light" | "dark" | "system";
  mp3_bitrate: number;
  capabilities: {
    playlists_enabled: boolean;
    transcoding_enabled: boolean;
    demo_data: boolean;
    file_ttl_seconds: number;
    storage_limit_bytes: number;
    storage_used_bytes: number;
    native_cap: number;
    default_cap: number;
  };
};

async function parse<T>(response: Response): Promise<T> {
  const text = await response.text();
  const data = text ? (JSON.parse(text) as T) : ({} as T);
  if (!response.ok) {
    const error = data as ErrorBody;
    throw Object.assign(new Error(error.error?.message || response.statusText), {
      status: response.status,
      body: error,
    });
  }
  return data;
}

function headers(csrf?: string, locale?: string): HeadersInit {
  const value: Record<string, string> = {
    "Content-Type": "application/json",
    "X-Requested-With": "seorap",
  };
  if (csrf) value["X-CSRF-Token"] = csrf;
  if (locale) value["X-Locale"] = locale;
  return value;
}

export const api = {
  async health(): Promise<boolean> {
    try {
      const response = await fetch("/healthz", { cache: "no-store" });
      return response.ok;
    } catch {
      return false;
    }
  },
  session: () => fetch("/api/v1/auth/session", { cache: "no-store" }).then((response) => parse<Session>(response)),
  bootstrap: (password: string) =>
    fetch("/api/v1/auth/bootstrap", { method: "POST", headers: headers(), body: JSON.stringify({ password }) }).then((r) => parse(r)),
  login: (password: string) =>
    fetch("/api/v1/auth/login", { method: "POST", headers: headers(), body: JSON.stringify({ password }) }).then((r) => parse<Session>(r)),
  logout: (csrf: string) => fetch("/api/v1/auth/logout", { method: "POST", headers: headers(csrf) }).then((r) => parse(r)),
  analyze: (url: string, csrf: string, locale: string) =>
    fetch("/api/v1/analyses", { method: "POST", headers: headers(csrf, locale), body: JSON.stringify({ url }) }).then((r) =>
      parse<Analysis>(r),
    ),
  settings: (csrf: string) => fetch("/api/v1/settings", { headers: headers(csrf) }).then((r) => parse<Settings>(r)),
  patchSettings: (csrf: string, body: Partial<Pick<Settings, "language" | "theme" | "mp3_bitrate">>) =>
    fetch("/api/v1/settings", { method: "PATCH", headers: headers(csrf), body: JSON.stringify(body) }).then((r) => parse<Settings>(r)),
  createJob: (csrf: string, locale: string, key: string, body: { analysis_id: string; choice_id: string; keep_on_server: boolean; conversion_consent: boolean }) =>
    fetch("/api/v1/jobs", { method: "POST", headers: { ...headers(csrf, locale), "Idempotency-Key": key }, body: JSON.stringify(body) }).then((r) =>
      parse<Job>(r),
    ),
  retryJob: (
    csrf: string,
    locale: string,
    parentId: string,
    key: string,
    body: { analysis_id: string; choice_id: string; keep_on_server: boolean; conversion_consent: boolean },
  ) =>
    fetch(`/api/v1/jobs/${parentId}/retry`, {
      method: "POST",
      headers: { ...headers(csrf, locale), "Idempotency-Key": key },
      body: JSON.stringify(body),
    }).then((r) => parse<Job>(r)),
  playlist: (csrf: string, locale: string, url: string) =>
    fetch("/api/v1/playlists/analyze", { method: "POST", headers: headers(csrf, locale), body: JSON.stringify({ url }) }).then((r) =>
      parse<PlaylistInspection>(r),
    ),
  jobs: (csrf: string) => fetch("/api/v1/jobs?limit=30", { headers: headers(csrf), cache: "no-store" }).then((r) => parse<{ jobs: Job[] }>(r)),
  job: (csrf: string, id: string) => fetch(`/api/v1/jobs/${id}`, { headers: headers(csrf), cache: "no-store" }).then((r) => parse<Job>(r)),
  cancel: (csrf: string, id: string) =>
    fetch(`/api/v1/jobs/${id}/cancel`, { method: "POST", headers: headers(csrf) }).then((r) => parse<Job>(r)),
  retention: (csrf: string, id: string, keep: boolean) =>
    fetch(`/api/v1/jobs/${id}/retention`, { method: "PATCH", headers: headers(csrf), body: JSON.stringify({ keep_on_server: keep }) }).then((r) =>
      parse<Job>(r),
    ),
  deleteFile: (csrf: string, id: string) =>
    fetch(`/api/v1/jobs/${id}/file`, { method: "DELETE", headers: headers(csrf) }).then((r) => parse<Job>(r)),
  deleteHistory: (csrf: string, id: string) => fetch(`/api/v1/jobs/${id}`, { method: "DELETE", headers: headers(csrf) }).then((r) => r.ok),
  diagnostics: (csrf: string) => fetch("/api/v1/diagnostics", { headers: headers(csrf) }).then((r) => parse<Record<string, unknown>>(r)),
};
