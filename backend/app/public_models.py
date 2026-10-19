"""Public response contracts used by FastAPI and generated TypeScript checks.

Additions are intentionally permitted so semantic engine facts can evolve without
removing existing fields; required identities and lifecycle fields are validated.
"""
from typing import Any, Literal
from pydantic import BaseModel, ConfigDict

class PublicModel(BaseModel):
    model_config = ConfigDict(extra='allow')

class PublicError(PublicModel):
    code: str
    message: str
    retryable: bool
    action: str
    retry_after_seconds: int | None = None

class PublicSource(PublicModel):
    video_id: str
    canonical_url: str
    title: str
    channel: str | None = None
    duration_seconds: float | None = None
    thumbnail_url: str | None = None

class PublicChoice(PublicModel):
    choice_id: str
    kind: Literal['mp4', 'mp3', 'original_audio']
    label: str
    container: str
    conversion_required: bool
    requires_consent: bool
    is_default: bool
    width: int | None = None
    height: int | None = None
    fps: float | None = None
    bitrate_kbps: int | None = None
    audio_language: str | None = None
    audio_role: str | None = None
    track_key: str | None = None
    estimated_bytes: int | None = None
    size_is_estimate: bool = True
    input_size_provenance: Literal['exact','approximate','unknown'] = 'unknown'
    output_size_provenance: Literal['exact','approximate','unknown'] = 'unknown'

class PublicAnalysis(PublicModel):
    analysis_id: str
    expires_at: str
    source: PublicSource
    audio_tracks: list[dict[str, Any]]
    choices: list[PublicChoice]
    effective_mp3_bitrate: int = 192

class PublicOutput(PublicModel):
    kind: str
    label: str
    container: str
    conversion_required: bool
    width: int | None = None
    height: int | None = None
    fps: float | None = None
    bitrate_kbps: int | None = None
    audio_language: str | None = None
    audio_role: str | None = None

class PublicArtifact(PublicModel):
    bytes: int
    filename: str
    mime: str
    expires_at: str | None = None

class PublicJob(PublicModel):
    id: str
    revision: int
    status: Literal['queued','running','succeeded','failed','cancelled','interrupted']
    phase: str | None
    cancel_requested: bool
    file_state: Literal['none','available','expired','deleted','missing']
    keep_on_server: bool
    source: PublicSource
    output: PublicOutput
    artifact: PublicArtifact | None
    error: PublicError | None
    progress: dict[str, Any] | None
    created_at: str
    updated_at: str
    queue_position: int | None = None
    retry_allowed: bool = False
    next_attempt_at: str | None = None

class PublicJobPage(PublicModel):
    jobs: list[PublicJob]
    total: int
    offset: int
    limit: int

class PublicSession(PublicModel):
    authenticated: bool
    bootstrapped: bool
    bootstrap_allowed: bool
    bootstrap_method: Literal['browser', 'cli'] | None
    password_required: bool = True
    csrf_token: str | None = None
    expires_at: str | None = None
    language: Literal['ko','en'] | None = None
    theme: Literal['light','dark','system'] | None = None

class PublicReadiness(PublicModel):
    processing_ready: bool
    worker_ready: bool
    dependencies_ready: bool
    reasons: list[str]

class PublicCapabilities(PublicModel):
    playlists_enabled: bool
    transcoding_enabled: bool
    demo_data: bool
    file_ttl_seconds: int
    storage_limit_bytes: int
    storage_used_bytes: int
    native_cap: int
    default_cap: int

class PublicSettings(PublicModel):
    language: Literal['ko', 'en']
    theme: Literal['light', 'dark', 'system']
    mp3_bitrate: Literal[128, 192, 320]
    capabilities: PublicCapabilities

class PublicPlaylist(PublicModel):
    playlist_id: str
    canonical_url: str
    limit: int
    limited: bool
    stopped_at_cap: bool
    entries: list[dict[str, Any]]
