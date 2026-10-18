"""Strict YouTube URL normalization. No network I/O."""

from __future__ import annotations

import ipaddress
import re
from dataclasses import dataclass
from urllib.parse import parse_qs, urlsplit

from app.errors import AppError

VIDEO_ID = re.compile(r"^[A-Za-z0-9_-]{11}$")
PLAYLIST_ID = re.compile(r"^[A-Za-z0-9_-]{10,80}$")
HOSTS = {
    "youtube.com",
    "www.youtube.com",
    "m.youtube.com",
    "music.youtube.com",
    "youtube-nocookie.com",
    "www.youtube-nocookie.com",
    "youtu.be",
    "www.youtu.be",
}
SHORT_HOSTS = {"youtu.be", "www.youtu.be"}
TIMESTAMP_KEYS = {"t", "start", "time_continue", "ab_channel"}


@dataclass(frozen=True)
class ParsedTarget:
    kind: str  # video | playlist
    video_id: str | None
    playlist_id: str | None
    canonical_url: str
    ignored_timestamp: bool
    ignored_playlist: bool


def _bad(code: str = "INVALID_URL") -> AppError:
    return AppError(code, 400)


def _unsupported() -> AppError:
    return AppError("UNSUPPORTED_URL", 400)


def parse_target(raw: str) -> ParsedTarget:
    if not isinstance(raw, str):
        raise _bad()
    if raw != raw.strip():
        raw = raw.strip()
    if not raw or len(raw) > 2048:
        raise _bad()
    if any(ord(ch) < 32 or ord(ch) == 127 for ch in raw):
        raise _bad()
    if "\\" in raw:
        raise _bad()
    if re.search(r"%(?![0-9A-Fa-f]{2})", raw):
        raise _bad()
    lowered = raw.lower()
    if any(token in lowered for token in ("%25", "%2e", "%2f", "%5c", "%00")):
        raise _bad()

    parts = urlsplit(raw)
    if parts.scheme.lower() not in {"http", "https"}:
        raise _bad()
    if parts.username or parts.password or "@" in raw.split("?", 1)[0]:
        raise _bad()
    host = (parts.hostname or "").lower()
    if not host or host.startswith("xn--") or any(ord(ch) > 127 for ch in host):
        raise _bad()
    try:
        ipaddress.ip_address(host.strip("[]"))
        raise _bad()
    except ValueError:
        pass
    if host not in HOSTS:
        raise AppError("UNSUPPORTED_URL", 400)
    try:
        port = parts.port
    except ValueError as exc:
        raise _bad() from exc
    if parts.scheme.lower() == "http" and port not in {None, 80}:
        raise _bad()
    if parts.scheme.lower() == "https" and port not in {None, 443}:
        raise _bad()

    path = parts.path or "/"
    if "//" in path or ".." in path:
        raise _bad()
    query = parse_qs(parts.query, keep_blank_values=False)
    ignored_timestamp = any(key in query for key in TIMESTAMP_KEYS)
    video = _first(query.get("v"))
    playlist = _first(query.get("list"))
    if playlist and not PLAYLIST_ID.match(playlist):
        raise _bad()
    if video and not VIDEO_ID.match(video):
        raise _bad()

    segments = [seg for seg in path.split("/") if seg]

    if host in SHORT_HOSTS:
        if len(segments) != 1 or not VIDEO_ID.match(segments[0]):
            raise _unsupported()
        return _video(segments[0], ignored_timestamp, playlist is not None)

    if not segments:
        raise _unsupported()

    head = segments[0].lower()
    if head in {"playlist"}:
        if not playlist:
            raise _unsupported()
        return _playlist(playlist)
    if head in {"channel", "c", "user", "feed", "results", "hashtag", "premium"} or head.startswith("@"):
        raise _unsupported()
    if head in {"shorts", "embed", "v", "live", "e"}:
        if len(segments) < 2 or not VIDEO_ID.match(segments[1]):
            raise _unsupported()
        if segments[1] in {"videoseries", "live_stream"}:
            raise _unsupported()
        return _video(segments[1], ignored_timestamp, playlist is not None)
    if head == "watch":
        if video:
            return _video(video, ignored_timestamp, playlist is not None)
        if playlist:
            return _playlist(playlist)
        raise _unsupported()
    raise _unsupported()


def _first(values: list[str] | None) -> str | None:
    if not values:
        return None
    return values[0]


def _video(video_id: str, ignored_timestamp: bool, ignored_playlist: bool) -> ParsedTarget:
    return ParsedTarget(
        kind="video",
        video_id=video_id,
        playlist_id=None,
        canonical_url=f"https://www.youtube.com/watch?v={video_id}",
        ignored_timestamp=ignored_timestamp,
        ignored_playlist=ignored_playlist,
    )


def _playlist(playlist_id: str) -> ParsedTarget:
    return ParsedTarget(
        kind="playlist",
        video_id=None,
        playlist_id=playlist_id,
        canonical_url=f"https://www.youtube.com/playlist?list={playlist_id}",
        ignored_timestamp=False,
        ignored_playlist=False,
    )


def require_video(raw: str) -> ParsedTarget:
    target = parse_target(raw)
    if target.kind != "video" or not target.video_id:
        raise _unsupported()
    return target


def require_playlist(raw: str) -> ParsedTarget:
    target = parse_target(raw)
    if target.kind != "playlist" or not target.playlist_id:
        # A watch URL that only identifies a video is not a playlist.
        if target.kind == "video":
            raise AppError(
                "UNSUPPORTED_URL",
                400,
                extra={
                    "message": "That URL identifies a video, not a playlist.",
                    "action": "Use a playlist URL, or analyze the video on the main form.",
                },
            )
        raise _unsupported()
    return target
