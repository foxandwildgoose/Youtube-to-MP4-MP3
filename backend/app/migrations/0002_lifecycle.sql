-- Additive migration: preserve jobs, sessions, preferences and kept artifacts.
CREATE TABLE storage_reservations (
  job_id TEXT PRIMARY KEY REFERENCES jobs(id) ON DELETE CASCADE,
  reserved_bytes INTEGER NOT NULL CHECK (reserved_bytes > 0),
  created_at TEXT NOT NULL,
  updated_at TEXT NOT NULL
);

ALTER TABLE jobs ADD COLUMN next_attempt_at TEXT;
ALTER TABLE jobs ADD COLUMN refresh_403_used INTEGER NOT NULL DEFAULT 0;
ALTER TABLE idempotency_keys ADD COLUMN expires_at TEXT;

CREATE INDEX idx_jobs_parent ON jobs(parent_job_id);
CREATE INDEX idx_jobs_analysis ON jobs(analysis_id);
CREATE INDEX idx_analyses_expiry ON analyses(expires_at);
CREATE INDEX idx_sessions_expiry ON sessions(expires_at, revoked_at);
CREATE INDEX idx_leases_job_expiry ON transfer_leases(job_id, expires_at);
CREATE INDEX idx_idempotency_expiry ON idempotency_keys(expires_at);
CREATE INDEX idx_jobs_retry ON jobs(status, next_attempt_at, created_at);

-- Automatic release also covers terminal transitions performed by old workers.
CREATE TRIGGER release_terminal_reservation
AFTER UPDATE OF status ON jobs
WHEN NEW.status NOT IN ('queued', 'running')
BEGIN
  DELETE FROM storage_reservations WHERE job_id = NEW.id;
END;
