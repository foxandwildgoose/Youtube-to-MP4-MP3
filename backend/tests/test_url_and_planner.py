"""T01 URL policy and T02/T03 planner contracts."""

import pytest

from app.config import load_settings
from app.errors import AppError
from app.services.format_planner import plan_outputs
from app.services.url_policy import parse_target, require_video


def test_valid_links_normalize():
    samples = {
        "https://www.youtube.com/watch?v=dQw4w9WgXcQ": "dQw4w9WgXcQ",
        "http://youtu.be/dQw4w9WgXcQ": "dQw4w9WgXcQ",
        "https://m.youtube.com/watch?v=dQw4w9WgXcQ&t=12s": "dQw4w9WgXcQ",
        "https://www.youtube.com/shorts/dQw4w9WgXcQ": "dQw4w9WgXcQ",
        "https://music.youtube.com/watch?v=dQw4w9WgXcQ&list=PLxxxx12345": "dQw4w9WgXcQ",
        "https://www.youtube.com/embed/dQw4w9WgXcQ": "dQw4w9WgXcQ",
        "https://www.youtube.com/live/dQw4w9WgXcQ": "dQw4w9WgXcQ",
    }
    for url, video_id in samples.items():
        parsed = require_video(url)
        assert parsed.video_id == video_id
        assert parsed.canonical_url == f"https://www.youtube.com/watch?v={video_id}"
        assert parsed.canonical_url.startswith("https://")
    timed = require_video("https://www.youtube.com/watch?v=dQw4w9WgXcQ&t=20")
    assert timed.ignored_timestamp is True
    listed = require_video("https://www.youtube.com/watch?v=dQw4w9WgXcQ&list=PLabcdefghij")
    assert listed.ignored_playlist is True


@pytest.mark.parametrize(
    "url",
    [
        "https://user:pass@www.youtube.com/watch?v=dQw4w9WgXcQ",
        "https://127.0.0.1/watch?v=dQw4w9WgXcQ",
        "https://192.168.1.10/watch?v=dQw4w9WgXcQ",
        "file:///tmp/video.mp4",
        "https://youtube.com.evil.com/watch?v=dQw4w9WgXcQ",
        "https://www.youtube.com/playlist?list=PLabcdefghij",
        "https://www.youtube.com/channel/UCxxxxxxxxxxxxxxxxxxxxxx",
        "https://www.youtube.com/results?search_query=cats",
        "https://www.youtube.com/watch?list=PLabcdefghij",
        "javascript:alert(1)",
        "https://www.youtube.com/watch?v=dQw4w9WgXcQ%2e%2e",
        "https://www.youtube.com\\watch?v=dQw4w9WgXcQ",
    ],
)
def test_rejected_urls(url):
    with pytest.raises(AppError):
        require_video(url)


def test_playlist_url_is_not_a_video():
    parsed = parse_target("https://www.youtube.com/playlist?list=PLabcdefghij")
    assert parsed.kind == "playlist"


def _streams_h264():
    return [
        {
            "kind": "video",
            "vcodec": "avc1.640028",
            "acodec": "none",
            "width": 1920,
            "height": 1080,
            "fps": 30,
            "pix_fmt": "yuv420p",
            "bit_depth": 8,
            "dynamic_range": "sdr",
        },
        {"kind": "audio", "vcodec": "none", "acodec": "mp4a.40.2", "language": "ko", "role": "original"},
    ]


def test_mp4_contract_and_caps():
    settings = load_settings()
    plan = plan_outputs(_streams_h264(), 12, settings)
    mp4 = [item for item in plan["choices"] if item["kind"] == "mp4" and not item["conversion"]]
    assert mp4
    assert all(item["output_vcodec"] == "h264" and item["output_acodec"] == "aac" for item in mp4)
    portrait = [
        {
            "kind": "muxed",
            "vcodec": "h264",
            "acodec": "aac",
            "width": 1080,
            "height": 1920,
            "fps": 30,
            "pix_fmt": "yuv420p",
            "bit_depth": 8,
            "dynamic_range": "sdr",
            "language": "ko",
            "role": "default",
        }
    ]
    planned = plan_outputs(portrait, 4, settings)
    chosen = [item for item in planned["choices"] if item["kind"] == "mp4" and not item["conversion"]]
    assert chosen and chosen[0]["portrait"] is True
    assert chosen[0]["output_width"] == 1080 and chosen[0]["output_height"] == 1920
    too_big = [
        {
            "kind": "muxed",
            "vcodec": "h264",
            "acodec": "aac",
            "width": 1440,
            "height": 2560,
            "fps": 30,
            "pix_fmt": "yuv420p",
            "bit_depth": 8,
            "dynamic_range": "sdr",
        }
    ]
    big = plan_outputs(too_big, 4, settings)
    copies = [item for item in big["choices"] if item["kind"] == "mp4" and not item["conversion"]]
    assert copies
    assert all(not item["is_default"] for item in copies)
    assert all(min(item["output_width"], item["output_height"]) <= 2160 for item in copies)


def test_vp9_is_not_labeled_h264_and_hdr_conversion_is_rejected():
    settings = load_settings()
    vp9 = [
        {
            "kind": "muxed",
            "vcodec": "vp9",
            "acodec": "opus",
            "width": 1280,
            "height": 720,
            "fps": 30,
            "pix_fmt": "yuv420p",
            "bit_depth": 8,
            "dynamic_range": "sdr",
            "language": "en",
            "role": "default",
        }
    ]
    plan = plan_outputs(vp9, 8, settings, transcoding_enabled=False)
    assert not any(item["kind"] == "mp4" for item in plan["choices"])
    assert any(item["kind"] == "original_audio" and item["output_acodec"] == "opus" for item in plan["choices"])
    enabled = plan_outputs(vp9, 8, settings, transcoding_enabled=True)
    converted = [item for item in enabled["choices"] if item["kind"] == "mp4"]
    assert converted and converted[0]["conversion"] and converted[0]["requires_consent"]
    assert converted[0]["output_vcodec"] == "h264"
    hdr = [
        {
            "kind": "muxed",
            "vcodec": "vp9",
            "acodec": "opus",
            "width": 1920,
            "height": 1080,
            "fps": 24,
            "pix_fmt": "yuv420p10le",
            "bit_depth": 10,
            "dynamic_range": "hdr",
            "color_transfer": "smpte2084",
        }
    ]
    hdr_plan = plan_outputs(hdr, 8, settings, transcoding_enabled=True)
    assert not any(item["kind"] == "mp4" for item in hdr_plan["choices"])
