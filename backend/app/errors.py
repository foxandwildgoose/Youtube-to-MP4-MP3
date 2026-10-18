"""Stable error envelope and localized user copy."""

from __future__ import annotations

from typing import Any


class AppError(Exception):
    def __init__(
        self,
        code: str,
        status: int,
        *,
        retryable: bool = False,
        retry_after: int | None = None,
        action_key: str | None = None,
        message_key: str | None = None,
        extra: dict[str, Any] | None = None,
    ) -> None:
        self.code = code
        self.status = status
        self.retryable = retryable
        self.retry_after = retry_after
        self.action_key = action_key or code
        self.message_key = message_key or code
        self.extra = extra or {}
        super().__init__(code)


MESSAGES: dict[str, dict[str, tuple[str, str]]] = {
    "INVALID_URL": {
        "ko": ("주소 형식이 올바르지 않습니다.", "YouTube 영상 주소를 다시 붙여 넣으세요."),
        "en": ("That address is not a valid URL.", "Paste a YouTube video URL."),
    },
    "UNSUPPORTED_URL": {
        "ko": ("이 주소는 단일 영상으로 처리할 수 없습니다.", "watch, youtu.be, Shorts 주소를 사용하세요. 재생목록·채널·검색은 제외됩니다."),
        "en": ("This URL is not a single video this app can process.", "Use a watch, youtu.be, or Shorts link. Playlists, channels, and search are rejected here."),
    },
    "SOURCE_UNAVAILABLE": {
        "ko": ("영상을 사용할 수 없습니다.", "공개되어 있고 끝난 영상인지 확인하세요. 진행 중이거나 예정된 라이브는 받을 수 없습니다."),
        "en": ("The video is not available.", "Check that it is public and finished. Active or upcoming livestreams are rejected."),
    },
    "SOURCE_AUTH_REQUIRED": {
        "ko": ("이 영상은 로그인이나 제한된 접근이 필요합니다.", "이 앱은 로그인 우회를 하지 않습니다. 받을 수 있는 공개 영상을 사용하세요."),
        "en": ("This video requires login or restricted access.", "This app does not bypass login. Use a public video you are allowed to save."),
    },
    "SOURCE_FORBIDDEN": {
        "ko": ("접근이 거부되었습니다. 멤버 전용, DRM, 또는 차단된 영상일 수 있습니다.", "다른 영상을 선택하세요. 접근 제한을 우회하지 않습니다."),
        "en": ("Access was denied. The video may be members-only, DRM-protected, or blocked.", "Choose another video. Access restrictions are not bypassed."),
    },
    "SOURCE_RATE_LIMITED": {
        "ko": ("YouTube가 요청을 잠시 제한했습니다.", "표시된 시간이 지난 뒤 다시 시도하세요."),
        "en": ("YouTube is rate-limiting requests.", "Wait for the indicated time, then try again."),
    },
    "FORMAT_UNAVAILABLE": {
        "ko": ("선택한 출력 형식을 만들 수 없습니다.", "분석을 다시 하고 목록에 있는 형식을 선택하세요."),
        "en": ("The selected output cannot be produced.", "Analyze again and choose an available output."),
    },
    "FORMAT_CHANGED": {
        "ko": ("선택한 형식을 더 이상 같은 조건으로 만들 수 없습니다.", "주소를 다시 분석하고 출력 형식을 고르세요. 품질을 몰래 낮추지 않습니다."),
        "en": ("The selected format is no longer available on the same terms.", "Analyze the URL again and choose an output. Quality is not silently reduced."),
    },
    "ANALYSIS_EXPIRED": {
        "ko": ("분석 결과가 만료되었습니다.", "주소를 다시 분석하세요."),
        "en": ("That analysis has expired.", "Analyze the URL again."),
    },
    "DEPENDENCY_MISSING": {
        "ko": ("필요한 변환 도구가 없습니다.", "FFmpeg, ffprobe, yt-dlp, Deno 설치 상태를 진단 화면에서 확인하세요."),
        "en": ("A required media tool is missing.", "Check FFmpeg, ffprobe, yt-dlp, and Deno in diagnostics."),
    },
    "WORKER_UNAVAILABLE": {
        "ko": ("작업 처리기가 응답하지 않습니다.", "worker 컨테이너가 실행 중인지 확인하세요. 대기 중인 작업은 유지됩니다."),
        "en": ("The worker is not available.", "Check that the worker container is running. Queued jobs are kept."),
    },
    "POSTPROCESS_FAILED": {
        "ko": ("변환 또는 병합에 실패했습니다.", "다시 시도하거나 다른 출력 형식을 선택하세요."),
        "en": ("Conversion or merging failed.", "Retry, or choose a different output."),
    },
    "OUTPUT_INVALID": {
        "ko": ("결과 파일이 기대하는 형식과 일치하지 않습니다.", "파일이 저장되지 않았습니다. 다른 출력 형식을 선택하세요."),
        "en": ("The output file did not match the expected format.", "Nothing was published. Choose a different output."),
    },
    "STORAGE_FULL": {
        "ko": ("저장 공간이 부족합니다.", "보관 파일을 지우거나 한도를 조정한 뒤 다시 시도하세요. 보관 중인 파일은 자동으로 지우지 않습니다."),
        "en": ("There is not enough storage.", "Delete kept files or raise the limit, then retry. Kept files are never removed automatically."),
    },
    "LIMIT_EXCEEDED": {
        "ko": ("길이, 크기, 또는 대기열 한도를 넘었습니다.", "더 짧은 영상을 선택하거나 대기 중인 작업이 끝난 뒤 다시 시도하세요."),
        "en": ("A duration, size, or queue limit was exceeded.", "Choose a shorter video, or wait until the queue has room."),
    },
    "JOB_TIMEOUT": {
        "ko": ("처리 제한 시간을 넘겼습니다.", "대기 시간은 포함되지 않습니다. 다시 시도할 수 있습니다."),
        "en": ("The active processing deadline was exceeded.", "Queue wait is not counted. You can retry."),
    },
    "FILE_EXPIRED": {
        "ko": ("서버의 파일이 만료되었습니다.", "같은 영상을 다시 분석해 새 파일을 만드세요. 이전 주소는 재사용하지 않습니다."),
        "en": ("The file on the server has expired.", "Analyze the video again to create a new file. The old link is not reused."),
    },
    "FILE_MISSING": {
        "ko": ("기록은 있지만 파일이 없습니다.", "새 작업을 만들어 다시 받으세요."),
        "en": ("The history entry exists, but the file is missing.", "Create a new job to fetch it again."),
    },
    "ENGINE_ERROR": {
        "ko": ("영상 엔진이 실패했습니다.", "잠시 뒤 다시 시도하세요. 계속되면 진단을 확인하세요."),
        "en": ("The media engine failed.", "Try again shortly. If it continues, check diagnostics."),
    },
    "INTERRUPTED": {
        "ko": ("작업 처리기가 중단되어 이 작업이 멈추었습니다.", "다시 시도하면 새로 분석한 뒤 처음부터 처리합니다."),
        "en": ("The worker stopped while this job was running.", "Retry analyzes the source again and starts over."),
    },
    "PLAYLISTS_DISABLED": {
        "ko": ("재생목록 분석이 꺼져 있습니다.", "단일 영상 주소를 사용하거나, 운영자가 ENABLE_PLAYLISTS를 켠 뒤에만 사용할 수 있습니다."),
        "en": ("Playlist inspection is disabled.", "Use a single video URL, or ask the operator to enable ENABLE_PLAYLISTS."),
    },
    "CONSENT_REQUIRED": {
        "ko": ("호환 MP4로 변환하려면 확인이 필요합니다.", "변환은 시간이 더 들고 화질이 떨어질 수 있습니다. 동의한 뒤에만 시작합니다."),
        "en": ("Converting to a compatible MP4 needs your confirmation.", "Conversion takes longer and may lose quality. It starts only after you agree."),
    },
    "TRANSCODING_DISABLED": {
        "ko": ("영상 변환이 서버에서 꺼져 있습니다.", "변환 없이 받을 수 있는 형식을 선택하세요."),
        "en": ("Video conversion is disabled on this server.", "Choose an output that does not need video conversion."),
    },
    "IDEMPOTENCY_CONFLICT": {
        "ko": ("같은 멱등 키가 다른 요청에 이미 쓰였습니다.", "새 작업을 만들려면 새 Idempotency-Key를 사용하세요."),
        "en": ("That idempotency key was already used for a different request.", "Use a new Idempotency-Key to create a different job."),
    },
    "IDEMPOTENCY_REQUIRED": {
        "ko": ("Idempotency-Key 헤더가 필요합니다.", "만들기와 다시 시도 요청에 키를 넣어 보내세요."),
        "en": ("The Idempotency-Key header is required.", "Send a key with create and retry requests."),
    },
    "PARENT_MISMATCH": {
        "ko": ("다시 시도할 영상이 원래 작업과 다릅니다.", "같은 영상으로 다시 분석하거나, 다른 영상은 새 작업으로 만드세요."),
        "en": ("The retry analysis is for a different video than the original job.", "Re-analyze the same video, or create an ordinary job for a different one."),
    },
    "UNAUTHORIZED": {
        "ko": ("로그인이 필요합니다.", "로컬 비밀번호로 로그인하세요."),
        "en": ("You need to sign in.", "Sign in with the local password."),
    },
    "CSRF_FAILED": {
        "ko": ("요청을 확인할 수 없습니다.", "페이지를 새로고침한 뒤 다시 시도하세요."),
        "en": ("The request could not be verified.", "Reload the page and try again."),
    },
    "LOGIN_THROTTLED": {
        "ko": ("로그인 시도가 너무 많습니다.", "잠시 기다린 뒤 다시 시도하세요."),
        "en": ("Too many sign-in attempts.", "Wait, then try again."),
    },
    "NOT_BOOTSTRAPPED": {
        "ko": ("아직 비밀번호가 없습니다.", "운영자가 비밀번호를 설정하기 전에는 열리지 않습니다."),
        "en": ("No password has been set.", "The app stays closed until the operator sets a password."),
    },
    "ALREADY_BOOTSTRAPPED": {
        "ko": ("비밀번호가 이미 설정되어 있습니다.", "로그인하거나 CLI로 비밀번호를 재설정하세요."),
        "en": ("A password is already set.", "Sign in, or reset the password with the CLI."),
    },
    "BAD_PASSWORD": {
        "ko": ("비밀번호가 올바르지 않습니다.", "다시 입력하세요."),
        "en": ("The password is not correct.", "Try again."),
    },
    "NOT_FOUND": {
        "ko": ("해당 항목이 없습니다.", "목록을 새로고침하세요."),
        "en": ("That item was not found.", "Refresh the list."),
    },
    "HISTORY_HAS_FILE": {
        "ko": ("파일이 아직 있어서 기록만 지울 수 없습니다.", "먼저 파일을 삭제한 뒤 기록을 지우세요."),
        "en": ("This history entry still has a file.", "Delete the file first, then remove the history entry."),
    },
    "BAD_REQUEST": {
        "ko": ("요청을 이해할 수 없습니다.", "입력 내용을 확인하세요."),
        "en": ("The request could not be understood.", "Check the fields and try again."),
    },
}


def localize(code: str, locale: str, fallback_message: str | None = None) -> tuple[str, str]:
    loc = "en" if locale == "en" else "ko"
    table = MESSAGES.get(code) or MESSAGES["ENGINE_ERROR"]
    message, action = table[loc]
    if fallback_message and code == "ENGINE_ERROR":
        return fallback_message, action
    return message, action


def envelope(error: AppError, locale: str) -> dict[str, Any]:
    message, action = localize(error.code, locale)
    if error.extra.get("message"):
        message = str(error.extra["message"])
    if error.extra.get("action"):
        action = str(error.extra["action"])
    body: dict[str, Any] = {
        "error": {
            "code": error.code,
            "message": message,
            "retryable": error.retryable,
            "action": action,
        }
    }
    if error.retry_after is not None:
        body["error"]["retry_after_seconds"] = error.retry_after
    return body
