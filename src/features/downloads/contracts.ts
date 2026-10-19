import type {
  PublicAnalysis,
  PublicCapabilities,
  PublicChoice,
  PublicError,
  PublicJob,
  PublicJobPage,
  PublicPlaylist,
  PublicReadiness,
  PublicSession,
  PublicSettings,
} from "./public-contracts.generated.ts";
export type ErrorBody = {
  error: PublicError & {
    code: string;
    message: string;
    retryable: boolean;
    action: string;
    retry_after_seconds?: number;
  };
};

export type Choice = PublicChoice & {
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
  input_bytes?: number | null;
  estimated_output_bytes?: number | null;
  expected_workspace_bytes?: number | null;
  encoded_width?: number | null;
  encoded_height?: number | null;
  rotation?: number | null;
  is_default: boolean;
};

export type Analysis = Omit<PublicAnalysis, "choices" | "source" | "audio_tracks"> & {
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
  effective_mp3_bitrate?: number;
  audio_tracks: {
    track_key?: string;
    codecs?: string[];
    representation_count?: number;
    language: string | null;
    role: string;
    codec: string;
  }[];
  choices: Choice[];
};

export type Job = Omit<PublicJob, "source" | "output" | "progress" | "error" | "artifact"> & {
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
    component?: string;
  } | null;
  error: ErrorBody["error"] | null;
  source: {
    title: string;
    channel?: string | null;
    canonical_url: string;
    video_id: string;
    duration_seconds?: number | null;
  };
  retry_allowed?: boolean;
  next_attempt_at?: string | null;
  attempts_used?: number;
  output: {
    kind: string;
    label: string;
    container: string;
    conversion_required: boolean;
    width?: number | null;
    height?: number | null;
    fps?: number | null;
    bitrate_kbps?: number | null;
    audio_language?: string | null;
    audio_role?: string | null;
    resolution_label?: string | null;
    audio_track_id?: string | null;
    conversion_mode?: string;
    vcodec?: string | null;
    acodec?: string | null;
  };
  artifact: { bytes: number; filename: string; mime: string; expires_at: string | null } | null;
  created_at: string;
  updated_at: string;
};

export type Session = PublicSession &
  (
    | {
        authenticated: false;
        bootstrapped: boolean;
        password_required?: boolean;
        bootstrap_allowed?: boolean;
        bootstrap_method?: "browser" | "cli" | null;
      }
    | {
        authenticated: true;
        bootstrapped: true;
        csrf_token: string;
        expires_at: string;
        language: "ko" | "en";
        theme: "light" | "dark" | "system";
        password_required?: boolean;
        bootstrap_allowed?: boolean;
        bootstrap_method?: "browser" | "cli" | null;
      }
  );

export type PlaylistInspection = Omit<PublicPlaylist, "entries"> & {
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
export type Settings = Omit<PublicSettings, "capabilities"> & {
  language: "ko" | "en";
  theme: "light" | "dark" | "system";
  mp3_bitrate: PublicSettings["mp3_bitrate"];
  capabilities: PublicCapabilities & {
    processing_ready?: boolean;
    max_source_duration_seconds?: number;
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

export type Readiness = PublicReadiness;
export type JobRequest = {
  analysis_id: string;
  choice_id: string;
  keep_on_server: boolean;
  conversion_consent: boolean;
};
export type JobsPage = Omit<PublicJobPage, "jobs"> & {
  jobs: Job[];
  total: number;
  offset: number;
  limit: number;
};
export type JobsQuery = {
  limit?: number;
  offset?: number;
  active?: boolean;
  search?: string;
  format?: string;
  status?: string;
  file_state?: string;
};

function record(value: unknown): value is Record<string, unknown> {
  return typeof value === "object" && value !== null && !Array.isArray(value);
}
function string(value: unknown): value is string {
  return typeof value === "string";
}
function finite(value: unknown): value is number {
  return typeof value === "number" && Number.isFinite(value);
}
const statuses = new Set(["queued", "running", "succeeded", "failed", "cancelled", "interrupted"]);
const fileStates = new Set(["none", "available", "expired", "deleted", "missing"]);
export function isJob(value: unknown): value is Job {
  if (
    !record(value) ||
    !string(value.id) ||
    !finite(value.revision) ||
    !Number.isInteger(value.revision) ||
    value.revision < 0 ||
    !string(value.status) ||
    !statuses.has(value.status) ||
    !string(value.file_state) ||
    !fileStates.has(value.file_state) ||
    typeof value.keep_on_server !== "boolean" ||
    typeof value.cancel_requested !== "boolean" ||
    !record(value.source) ||
    !string(value.source.title) ||
    !string(value.source.video_id) ||
    !string(value.source.canonical_url) ||
    !record(value.output) ||
    !string(value.output.kind) ||
    !string(value.output.label) ||
    !string(value.output.container) ||
    typeof value.output.conversion_required !== "boolean" ||
    !string(value.created_at) ||
    !Number.isFinite(Date.parse(value.created_at)) ||
    !string(value.updated_at) ||
    !Number.isFinite(Date.parse(value.updated_at))
  )
    return false;
  if (
    value.artifact !== null &&
    (!record(value.artifact) ||
      !finite(value.artifact.bytes) ||
      value.artifact.bytes < 0 ||
      !string(value.artifact.filename) ||
      !string(value.artifact.mime))
  )
    return false;
  if (value.progress !== null && !record(value.progress)) return false;
  return true;
}
export function isSession(value: unknown): value is Session {
  if (
    !record(value) ||
    typeof value.authenticated !== "boolean" ||
    typeof value.bootstrapped !== "boolean" ||
    typeof value.bootstrap_allowed !== "boolean" ||
    !["browser", "cli", null].includes(value.bootstrap_method as string | null)
  )
    return false;
  return (
    !value.authenticated ||
    (string(value.csrf_token) &&
      value.csrf_token.length > 0 &&
      string(value.expires_at) &&
      Number.isFinite(Date.parse(value.expires_at)) &&
      ["ko", "en"].includes(String(value.language)) &&
      ["light", "dark", "system"].includes(String(value.theme)))
  );
}
export function isAnalysis(value: unknown): value is Analysis {
  return (
    record(value) &&
    string(value.analysis_id) &&
    string(value.expires_at) &&
    Number.isFinite(Date.parse(value.expires_at)) &&
    record(value.source) &&
    string(value.source.video_id) &&
    string(value.source.canonical_url) &&
    string(value.source.title) &&
    Array.isArray(value.audio_tracks) &&
    Array.isArray(value.choices) &&
    value.choices.length <= 2000 &&
    value.choices.every(
      (choice) =>
        record(choice) &&
        string(choice.choice_id) &&
        ["mp4", "mp3", "original_audio"].includes(String(choice.kind)) &&
        string(choice.label) &&
        typeof choice.requires_consent === "boolean" &&
        typeof choice.is_default === "boolean" &&
        string(choice.container),
    )
  );
}
export function isSettings(value: unknown): value is Settings {
  return (
    record(value) &&
    ["ko", "en"].includes(String(value.language)) &&
    ["light", "dark", "system"].includes(String(value.theme)) &&
    [128, 192, 320].includes(Number(value.mp3_bitrate)) &&
    record(value.capabilities) &&
    typeof value.capabilities.playlists_enabled === "boolean" &&
    typeof value.capabilities.transcoding_enabled === "boolean" &&
    finite(value.capabilities.storage_used_bytes) &&
    finite(value.capabilities.storage_limit_bytes)
  );
}
export function isJobsPage(value: unknown): value is JobsPage {
  return (
    record(value) &&
    Array.isArray(value.jobs) &&
    value.jobs.length <= 100 &&
    value.jobs.every(isJob) &&
    finite(value.total) &&
    value.total >= 0 &&
    finite(value.offset) &&
    finite(value.limit)
  );
}
export function isReadiness(value: unknown): value is Readiness {
  return (
    record(value) &&
    typeof value.processing_ready === "boolean" &&
    typeof value.worker_ready === "boolean" &&
    typeof value.dependencies_ready === "boolean" &&
    Array.isArray(value.reasons) &&
    value.reasons.every(string)
  );
}
export function isPlaylist(value: unknown): value is PlaylistInspection {
  return (
    record(value) &&
    string(value.playlist_id) &&
    string(value.canonical_url) &&
    Array.isArray(value.entries) &&
    value.entries.length <= 200 &&
    value.entries.every(
      (entry) =>
        record(entry) &&
        typeof entry.available === "boolean" &&
        finite(entry.position) &&
        (entry.canonical_url === null || string(entry.canonical_url)),
    )
  );
}

// Compile-time conformance to the generated FastAPI response models.
type Conforms<T extends U, U> = T;
export type ContractConformance = [
  Conforms<Analysis, PublicAnalysis>,
  Conforms<Choice, PublicChoice>,
  Conforms<Job, PublicJob>,
  Conforms<JobsPage, PublicJobPage>,
  Conforms<Session, PublicSession>,
  Conforms<Settings, PublicSettings>,
  Conforms<PlaylistInspection, PublicPlaylist>,
];
