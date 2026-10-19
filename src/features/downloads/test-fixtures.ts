import type { Job } from "./contracts.ts";
export function fixtureJob(id = "one", revision = 1, status: Job["status"] = "running"): Job {
  return {
    id,
    revision,
    status,
    phase: "downloading",
    cancel_requested: false,
    queue_position: null,
    file_state: "none",
    keep_on_server: false,
    progress: null,
    error: null,
    source: {
      title: `Source ${id}`,
      canonical_url: "https://www.youtube.com/watch?v=fixture001",
      video_id: "fixture001",
    },
    output: { kind: "mp4", label: "1080p", container: "mp4", conversion_required: false },
    artifact: null,
    created_at: "2026-10-18T00:00:00Z",
    updated_at: "2026-10-18T00:00:00Z",
  };
}
