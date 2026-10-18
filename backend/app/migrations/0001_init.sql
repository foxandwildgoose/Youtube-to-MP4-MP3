CREATE TABLE IF NOT EXISTS operator (
  id INTEGER PRIMARY KEY CHECK (id = 1),
  password_hash TEXT NOT NULL,
  created_at TEXT NOT NULL,
  updated_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS sessions (
  id TEXT PRIMARY KEY,
  token_hash TEXT NOT NULL UNIQUE,
  csrf_secret TEXT NOT NULL,
  created_at TEXT NOT NULL,
  expires_at TEXT NOT NULL,
  revoked_at TEXT,
  last_seen_at TEXT
);

CREATE TABLE IF NOT EXISTS login_attempts (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  ip TEXT NOT NULL,
  at TEXT NOT NULL,
  success INTEGER NOT NULL
);

CREATE TABLE IF NOT EXISTS preferences (
  id INTEGER PRIMARY KEY CHECK (id = 1),
  language TEXT NOT NULL DEFAULT 'ko',
  theme TEXT NOT NULL DEFAULT 'system',
  mp3_bitrate INTEGER NOT NULL DEFAULT 192,
  updated_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS analyses (
  id TEXT PRIMARY KEY,
  canonical_url TEXT NOT NULL,
  video_id TEXT NOT NULL,
  metadata_json TEXT NOT NULL,
  choices_json TEXT NOT NULL,
  created_at TEXT NOT NULL,
  expires_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS idempotency_keys (
  key TEXT PRIMARY KEY,
  request_hash TEXT NOT NULL,
  job_id TEXT,
  created_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS jobs (
  id TEXT PRIMARY KEY,
  parent_job_id TEXT,
  analysis_id TEXT,
  status TEXT NOT NULL,
  phase TEXT,
  cancel_requested_at TEXT,
  file_state TEXT NOT NULL DEFAULT 'none',
  keep_on_server INTEGER NOT NULL DEFAULT 0,
  revision INTEGER NOT NULL DEFAULT 0,
  contract_json TEXT NOT NULL,
  source_json TEXT NOT NULL,
  progress_json TEXT,
  error_json TEXT,
  created_at TEXT NOT NULL,
  updated_at TEXT NOT NULL,
  started_at TEXT,
  finished_at TEXT,
  worker_id TEXT,
  claimed_at TEXT,
  file_expires_at TEXT,
  artifact_json TEXT,
  attempts_used INTEGER NOT NULL DEFAULT 0,
  active_deadline_at TEXT,
  history_hidden INTEGER NOT NULL DEFAULT 0
);

CREATE INDEX IF NOT EXISTS idx_jobs_status_created ON jobs (status, created_at);
CREATE INDEX IF NOT EXISTS idx_jobs_file_expiry ON jobs (file_state, file_expires_at);

CREATE TABLE IF NOT EXISTS provider_cooldown (
  provider TEXT PRIMARY KEY,
  until_at TEXT NOT NULL,
  reason TEXT
);

CREATE TABLE IF NOT EXISTS transfer_leases (
  id TEXT PRIMARY KEY,
  job_id TEXT NOT NULL,
  expires_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS worker_heartbeat (
  id INTEGER PRIMARY KEY CHECK (id = 1),
  worker_id TEXT,
  beat_at TEXT,
  pid INTEGER
);

CREATE TABLE IF NOT EXISTS analysis_slots (
  id TEXT PRIMARY KEY,
  owner TEXT NOT NULL,
  expires_at TEXT NOT NULL
);
