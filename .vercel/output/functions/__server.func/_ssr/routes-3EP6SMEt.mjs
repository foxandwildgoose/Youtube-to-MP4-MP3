import { i as __toESM } from "../_runtime.mjs";
import { K as require_react, b as require_jsx_runtime } from "../_libs/@tanstack/react-router+[...].mjs";
import { a as Languages, c as Archive, i as LoaderCircle, n as Sun, o as Download, r as Moon, s as ClipboardPaste } from "../_libs/lucide-react.mjs";
//#region node_modules/.nitro/vite/services/ssr/assets/routes-3EP6SMEt.js
var import_react = /* @__PURE__ */ __toESM(require_react());
var import_jsx_runtime = require_jsx_runtime();
async function parse(response) {
	const text = await response.text();
	const data = text ? JSON.parse(text) : {};
	if (!response.ok) {
		const error = data;
		throw Object.assign(new Error(error.error?.message || response.statusText), {
			status: response.status,
			body: error
		});
	}
	return data;
}
function headers(csrf, locale) {
	const value = {
		"Content-Type": "application/json",
		"X-Requested-With": "seorap"
	};
	if (csrf) value["X-CSRF-Token"] = csrf;
	if (locale) value["X-Locale"] = locale;
	return value;
}
var api = {
	async health() {
		try {
			return (await fetch("/healthz", { cache: "no-store" })).ok;
		} catch {
			return false;
		}
	},
	session: () => fetch("/api/v1/auth/session", { cache: "no-store" }).then((response) => parse(response)),
	bootstrap: (password) => fetch("/api/v1/auth/bootstrap", {
		method: "POST",
		headers: headers(),
		body: JSON.stringify({ password })
	}).then((r) => parse(r)),
	login: (password) => fetch("/api/v1/auth/login", {
		method: "POST",
		headers: headers(),
		body: JSON.stringify({ password })
	}).then((r) => parse(r)),
	logout: (csrf) => fetch("/api/v1/auth/logout", {
		method: "POST",
		headers: headers(csrf)
	}).then((r) => parse(r)),
	analyze: (url, csrf, locale) => fetch("/api/v1/analyses", {
		method: "POST",
		headers: headers(csrf, locale),
		body: JSON.stringify({ url })
	}).then((r) => parse(r)),
	settings: (csrf) => fetch("/api/v1/settings", { headers: headers(csrf) }).then((r) => parse(r)),
	patchSettings: (csrf, body) => fetch("/api/v1/settings", {
		method: "PATCH",
		headers: headers(csrf),
		body: JSON.stringify(body)
	}).then((r) => parse(r)),
	createJob: (csrf, locale, key, body) => fetch("/api/v1/jobs", {
		method: "POST",
		headers: {
			...headers(csrf, locale),
			"Idempotency-Key": key
		},
		body: JSON.stringify(body)
	}).then((r) => parse(r)),
	retryJob: (csrf, locale, parentId, key, body) => fetch(`/api/v1/jobs/${parentId}/retry`, {
		method: "POST",
		headers: {
			...headers(csrf, locale),
			"Idempotency-Key": key
		},
		body: JSON.stringify(body)
	}).then((r) => parse(r)),
	playlist: (csrf, locale, url) => fetch("/api/v1/playlists/analyze", {
		method: "POST",
		headers: headers(csrf, locale),
		body: JSON.stringify({ url })
	}).then((r) => parse(r)),
	jobs: (csrf) => fetch("/api/v1/jobs?limit=30", {
		headers: headers(csrf),
		cache: "no-store"
	}).then((r) => parse(r)),
	job: (csrf, id) => fetch(`/api/v1/jobs/${id}`, {
		headers: headers(csrf),
		cache: "no-store"
	}).then((r) => parse(r)),
	cancel: (csrf, id) => fetch(`/api/v1/jobs/${id}/cancel`, {
		method: "POST",
		headers: headers(csrf)
	}).then((r) => parse(r)),
	retention: (csrf, id, keep) => fetch(`/api/v1/jobs/${id}/retention`, {
		method: "PATCH",
		headers: headers(csrf),
		body: JSON.stringify({ keep_on_server: keep })
	}).then((r) => parse(r)),
	deleteFile: (csrf, id) => fetch(`/api/v1/jobs/${id}/file`, {
		method: "DELETE",
		headers: headers(csrf)
	}).then((r) => parse(r)),
	deleteHistory: (csrf, id) => fetch(`/api/v1/jobs/${id}`, {
		method: "DELETE",
		headers: headers(csrf)
	}).then((r) => r.ok),
	diagnostics: (csrf) => fetch("/api/v1/diagnostics", { headers: headers(csrf) }).then((r) => parse(r))
};
var copy = {
	ko: {
		name: "서랍",
		tagline: "영상 하나, 파일 하나.",
		notice: "받을 권리가 있는 자료만 저장하세요. 저작권과 플랫폼 약관을 지키세요. 개인적·비상업적 사용만으로 허락이 되지는 않습니다.",
		terms: "YouTube 약관",
		ownUploads: "내 업로드 받기",
		analyze: "분석",
		urlLabel: "YouTube 주소",
		urlHint: "watch, youtu.be, Shorts 주소를 붙여 넣으세요. 재생 위치는 무시하고 영상 전체를 받습니다.",
		paste: "붙여넣기",
		offlineTitle: "Backend not connected",
		offlineBody: "이 미리보기에서 변환 서버에 연결하지 못했습니다. 성공한 다운로드로 표시하지 않습니다.",
		checking: "연결을 확인하고 있습니다",
		setupTitle: "로컬 비밀번호",
		setupBody: "이 앱은 한 사람의 비밀번호로만 열립니다. 10자 이상으로 정하세요.",
		password: "비밀번호",
		confirm: "비밀번호 확인",
		savePassword: "비밀번호 저장",
		loginTitle: "열기",
		login: "로그인",
		logout: "로그아웃",
		mismatch: "비밀번호가 같지 않습니다.",
		theme: "테마",
		themeSystem: "시스템",
		themeLight: "밝게",
		themeDark: "어둡게",
		language: "언어",
		metadata: "영상 정보",
		channel: "채널",
		duration: "길이",
		source: "원본 페이지",
		noThumb: "미리보기 없음",
		timestamp: "주소의 재생 위치는 무시하고 영상 전체를 저장합니다.",
		playlistIgnored: "재생목록 매개변수는 무시하고 이 영상만 처리합니다.",
		tabMp4: "호환 MP4",
		tabMp3: "MP3",
		tabOriginal: "원본 오디오",
		noChoice: "이 소스에는 해당 출력이 없습니다.",
		details: "기술 정보",
		conversionNote: "변환은 더 오래 걸리고 화질이 떨어질 수 있습니다. 속도를 미리 약속하지 않습니다.",
		bitrateNote: "출력 비트레이트를 높여도 원본에 없는 디테일은 돌아오지 않습니다.",
		originalNote: "원본은 플랫폼이 제공하는 오디오 스트림입니다. 업로더의 마스터 파일이 아닙니다.",
		consent: "호환 MP4로 변환하는 데 동의합니다",
		confirmLabel: "선택한 출력",
		copy: "다시 인코딩하지 않고 복사합니다",
		convert: "변환이 필요합니다",
		create: "파일 만들기",
		creating: "넣는 중",
		jobs: "작업",
		history: "기록",
		emptyJobs: "진행 중인 작업이 없습니다.",
		emptyHistory: "아직 기록이 없습니다.",
		cancel: "취소",
		cancelling: "취소를 요청했습니다",
		download: "이 기기에 받기",
		stored: "서버에 보관됨",
		folder: "서버 폴더",
		logicalFolder: "보관함",
		keep: "서버에 보관",
		keepHint: "보관 파일도 용량에 포함되며, 공간을 만들기 위해 자동으로 지우지 않습니다.",
		expire: "만료 허용",
		deleteFile: "파일 삭제",
		deleteHistory: "기록만 삭제",
		retry: "새로 분석해서 다시 만들기",
		retryHint: "다음 파일은 이 작업의 새 시도입니다. 같은 영상을 다시 분석해야 합니다.",
		clearRetry: "새 파일로 만들기",
		playlistTitle: "재생목록",
		playlistHint: "처음 20개만 살펴봅니다. 자동으로 고르지 않으며, 고른 항목은 각각 분석한 뒤에만 작업이 됩니다.",
		playlistLimited: "목록은 여기서 멈춥니다. 뒤의 항목은 가져오지 않습니다.",
		playlistUnavailable: "이 항목은 받을 수 없습니다",
		playlistUse: "이 영상 분석",
		speed: "속도",
		eta: "남은 시간",
		demo: "Demo data",
		quota: "사용 중인 용량",
		phase: {
			resolving: "형식 확인",
			downloading: "받는 중",
			merging: "합치는 중",
			transcoding: "변환 중",
			verifying: "검사 중"
		},
		status: {
			queued: "대기",
			running: "처리 중",
			succeeded: "완료",
			failed: "실패",
			cancelled: "취소됨",
			interrupted: "중단됨"
		},
		fileState: {
			none: "파일 없음",
			available: "받을 수 있음",
			expired: "만료됨",
			deleted: "삭제됨",
			missing: "파일 분실"
		},
		queue: "대기 순번",
		unknownProgress: "전체 크기를 아직 모릅니다",
		connection: "연결",
		live: "실시간",
		polling: "폴링으로 확인 중",
		diagnostics: "진단",
		close: "닫기",
		portrait: "세로 영상",
		estimate: "예상",
		unknown: "알 수 없음",
		audioLanguage: "오디오 언어",
		role: {
			original: "원본 트랙",
			default: "기본 트랙",
			alternate: "다른 트랙"
		}
	},
	en: {
		name: "Seorap",
		tagline: "One video, one file.",
		notice: "Download only material you are allowed to download and use. Respect copyright and the platform's terms. Personal or noncommercial use alone does not grant permission.",
		terms: "YouTube terms",
		ownUploads: "Your own uploads",
		analyze: "Analyze",
		urlLabel: "YouTube URL",
		urlHint: "Paste a watch, youtu.be, or Shorts link. Timestamps are ignored and the full video is saved.",
		paste: "Paste",
		offlineTitle: "Backend not connected",
		offlineBody: "This preview cannot reach the processing server. Nothing here is reported as a successful download.",
		checking: "Checking the connection",
		setupTitle: "Local password",
		setupBody: "This app opens with one password. Choose at least 10 characters.",
		password: "Password",
		confirm: "Confirm password",
		savePassword: "Save password",
		loginTitle: "Open",
		login: "Sign in",
		logout: "Sign out",
		mismatch: "The passwords do not match.",
		theme: "Theme",
		themeSystem: "System",
		themeLight: "Light",
		themeDark: "Dark",
		language: "Language",
		metadata: "Video",
		channel: "Channel",
		duration: "Duration",
		source: "Source page",
		noThumb: "No preview",
		timestamp: "The timestamp in the URL is ignored. The full video is saved.",
		playlistIgnored: "A playlist parameter was ignored. Only this video is processed.",
		tabMp4: "Compatible MP4",
		tabMp3: "MP3",
		tabOriginal: "Original audio",
		noChoice: "This source has no output of that kind.",
		details: "Technical details",
		conversionNote: "Conversion takes longer and may lose quality. No processing speed is promised.",
		bitrateNote: "A higher output bitrate cannot restore detail that was not in the source.",
		originalNote: "Original means the audio stream the platform offers, not the uploader's master file.",
		consent: "I agree to convert this to a compatible MP4",
		confirmLabel: "Selected output",
		copy: "Copied without re-encoding",
		convert: "Conversion is required",
		create: "Create file",
		creating: "Submitting",
		jobs: "Jobs",
		history: "History",
		emptyJobs: "No job is running.",
		emptyHistory: "No history yet.",
		cancel: "Cancel",
		cancelling: "Cancellation requested",
		download: "Download to this device",
		stored: "Stored on server",
		folder: "Server folder",
		logicalFolder: "Library",
		keep: "Keep on server",
		keepHint: "Kept files still count toward the quota and are never deleted automatically to free space.",
		expire: "Allow expiry",
		deleteFile: "Delete file",
		deleteHistory: "Remove history only",
		retry: "Analyze again and create a new file",
		retryHint: "The next file is a new attempt at this job. Analyze the same video again.",
		clearRetry: "Create an unrelated file",
		playlistTitle: "Playlist",
		playlistHint: "Only the first 20 positions are inspected. Nothing is selected automatically, and each chosen item is analyzed before it becomes its own job.",
		playlistLimited: "Inspection stops here. Later entries are not fetched.",
		playlistUnavailable: "This entry cannot be used",
		playlistUse: "Analyze this video",
		speed: "Speed",
		eta: "Time left",
		demo: "Demo data",
		quota: "Storage used",
		phase: {
			resolving: "Resolving",
			downloading: "Downloading",
			merging: "Merging",
			transcoding: "Converting",
			verifying: "Verifying"
		},
		status: {
			queued: "Queued",
			running: "Running",
			succeeded: "Ready",
			failed: "Failed",
			cancelled: "Cancelled",
			interrupted: "Interrupted"
		},
		fileState: {
			none: "No file",
			available: "Available",
			expired: "Expired",
			deleted: "Deleted",
			missing: "Missing"
		},
		queue: "Queue position",
		unknownProgress: "Total size is not known yet",
		connection: "Connection",
		live: "Live",
		polling: "Checking by polling",
		diagnostics: "Diagnostics",
		close: "Close",
		portrait: "Portrait",
		estimate: "Estimate",
		unknown: "Unknown",
		audioLanguage: "Audio language",
		role: {
			original: "Original track",
			default: "Default track",
			alternate: "Alternate track"
		}
	}
};
function translate(locale) {
	return copy[locale];
}
function formatDuration(seconds) {
	if (seconds == null || Number.isNaN(seconds)) return "—";
	const total = Math.round(seconds);
	const h = Math.floor(total / 3600);
	const m = Math.floor(total % 3600 / 60);
	const s = total % 60;
	if (h) return `${h}:${String(m).padStart(2, "0")}:${String(s).padStart(2, "0")}`;
	return `${m}:${String(s).padStart(2, "0")}`;
}
function formatBytes(value) {
	if (value == null) return "—";
	const units = [
		"B",
		"KB",
		"MB",
		"GB"
	];
	let n = value;
	let i = 0;
	while (n >= 1024 && i < units.length - 1) {
		n /= 1024;
		i += 1;
	}
	return `${n.toFixed(n >= 10 || i === 0 ? 0 : 1)} ${units[i]}`;
}
function applyTheme(theme) {
	const dark = theme === "dark" || theme === "system" && window.matchMedia("(prefers-color-scheme: dark)").matches;
	document.documentElement.dataset.theme = dark ? "dark" : "light";
	localStorage.setItem("seorap-theme", theme);
}
function DownloaderApp() {
	const [locale, setLocale] = (0, import_react.useState)("ko");
	const t = translate(locale);
	const [gate, setGate] = (0, import_react.useState)("boot");
	const [session, setSession] = (0, import_react.useState)(null);
	const [settings, setSettings] = (0, import_react.useState)(null);
	const [password, setPassword] = (0, import_react.useState)("");
	const [confirm, setConfirm] = (0, import_react.useState)("");
	const [formError, setFormError] = (0, import_react.useState)(null);
	const [url, setUrl] = (0, import_react.useState)("");
	const [urlError, setUrlError] = (0, import_react.useState)(null);
	const [busy, setBusy] = (0, import_react.useState)(false);
	const [analysis, setAnalysis] = (0, import_react.useState)(null);
	const [tab, setTab] = (0, import_react.useState)("mp4");
	const [choiceId, setChoiceId] = (0, import_react.useState)(null);
	const [keep, setKeep] = (0, import_react.useState)(false);
	const [consent, setConsent] = (0, import_react.useState)(false);
	const [jobs, setJobs] = (0, import_react.useState)([]);
	const [parentId, setParentId] = (0, import_react.useState)(null);
	const [playlistUrl, setPlaylistUrl] = (0, import_react.useState)("");
	const [playlist, setPlaylist] = (0, import_react.useState)(null);
	const [playlistError, setPlaylistError] = (0, import_react.useState)(null);
	const [live, setLive] = (0, import_react.useState)("polling");
	const [diag, setDiag] = (0, import_react.useState)(null);
	const [theme, setTheme] = (0, import_react.useState)("system");
	const csrf = session && session.authenticated ? session.csrf_token : "";
	(0, import_react.useEffect)(() => {
		let stop = false;
		api.health().then(async (ok) => {
			if (stop) return;
			if (!ok) {
				setGate("offline");
				return;
			}
			try {
				const current = await api.session();
				if (stop) return;
				setSession(current);
				setGate(current.authenticated ? "ready" : current.bootstrapped ? "login" : "setup");
			} catch {
				if (!stop) setGate("offline");
			}
		});
		return () => {
			stop = true;
		};
	}, []);
	(0, import_react.useEffect)(() => {
		document.documentElement.lang = locale;
		localStorage.setItem("seorap-lang", locale);
	}, [locale]);
	(0, import_react.useEffect)(() => {
		if (gate !== "ready" || !csrf) return;
		api.settings(csrf).then((value) => {
			setSettings(value);
			setLocale(value.language);
			setTheme(value.theme);
			applyTheme(value.theme);
		}).catch(() => void 0);
		refreshJobs(csrf);
	}, [gate, csrf]);
	(0, import_react.useEffect)(() => {
		if (theme) applyTheme(theme);
	}, [theme]);
	const active = jobs.filter((job) => job.status === "queued" || job.status === "running");
	const history = jobs.filter((job) => job.status !== "queued" && job.status !== "running");
	async function refreshJobs(token = csrf) {
		if (!token) return;
		const list = await api.jobs(token);
		setJobs(list.jobs);
	}
	async function onSetup(event) {
		event.preventDefault();
		setFormError(null);
		if (password !== confirm) {
			setFormError(t.mismatch);
			return;
		}
		setBusy(true);
		try {
			await api.bootstrap(password);
			const next = await api.login(password);
			setSession(next);
			setPassword("");
			setConfirm("");
			setGate("ready");
		} catch (error) {
			setFormError(messageOf(error));
		} finally {
			setBusy(false);
		}
	}
	async function onLogin(event) {
		event.preventDefault();
		setBusy(true);
		setFormError(null);
		try {
			const next = await api.login(password);
			setSession(next);
			setPassword("");
			setGate("ready");
		} catch (error) {
			setFormError(messageOf(error));
		} finally {
			setBusy(false);
		}
	}
	async function onAnalyze(event) {
		event.preventDefault();
		setUrlError(null);
		setBusy(true);
		try {
			const next = await api.analyze(url.trim(), csrf, locale);
			setAnalysis(next);
			if (parentId) {
				const parent = jobs.find((job) => job.id === parentId);
				if (parent?.source.video_id && parent.source.video_id !== next.source.video_id) setParentId(null);
			}
			const first = next.choices.find((item) => item.is_default) || next.choices[0];
			setTab(first?.kind || "mp4");
			setChoiceId(first?.choice_id || null);
			setConsent(false);
		} catch (error) {
			setAnalysis(null);
			setUrlError(messageOf(error));
		} finally {
			setBusy(false);
		}
	}
	async function onCreate() {
		if (!analysis || !choiceId) return;
		setBusy(true);
		setUrlError(null);
		try {
			const body = {
				analysis_id: analysis.analysis_id,
				choice_id: choiceId,
				keep_on_server: keep,
				conversion_consent: consent
			};
			const key = crypto.randomUUID();
			const job = parentId ? await api.retryJob(csrf, locale, parentId, key, body) : await api.createJob(csrf, locale, key, body);
			setParentId(null);
			setJobs((current) => [job, ...current.filter((item) => item.id !== job.id)]);
			watch(job.id);
		} catch (error) {
			setUrlError(messageOf(error));
		} finally {
			setBusy(false);
		}
	}
	function watch(id) {
		const source = new EventSource(`/api/v1/jobs/${id}/events`);
		setLive("live");
		source.addEventListener("snapshot", (event) => {
			const job = JSON.parse(event.data);
			setJobs((current) => [job, ...current.filter((item) => item.id !== job.id)]);
			if ([
				"succeeded",
				"failed",
				"cancelled",
				"interrupted"
			].includes(job.status)) source.close();
		});
		source.onerror = () => {
			source.close();
			setLive("polling");
			api.job(csrf, id).then((job) => {
				setJobs((current) => [job, ...current.filter((item) => item.id !== job.id)]);
			}).catch(() => void 0);
		};
	}
	const choices = (0, import_react.useMemo)(() => analysis?.choices.filter((item) => item.kind === tab) || [], [analysis, tab]);
	const selected = analysis?.choices.find((item) => item.choice_id === choiceId) || null;
	return /* @__PURE__ */ (0, import_jsx_runtime.jsxs)("main", {
		className: "mx-auto flex min-h-screen w-full max-w-3xl flex-col gap-6 px-4 py-6 sm:px-6",
		children: [
			/* @__PURE__ */ (0, import_jsx_runtime.jsxs)("header", {
				className: "flex items-center justify-between gap-3",
				children: [/* @__PURE__ */ (0, import_jsx_runtime.jsxs)("div", {
					className: "flex items-center gap-3",
					children: [/* @__PURE__ */ (0, import_jsx_runtime.jsx)("span", {
						className: "bg-primary text-primary-fg grid size-11 place-items-center rounded-md",
						"aria-hidden": "true",
						children: /* @__PURE__ */ (0, import_jsx_runtime.jsx)(Archive, { className: "size-5" })
					}), /* @__PURE__ */ (0, import_jsx_runtime.jsxs)("div", { children: [/* @__PURE__ */ (0, import_jsx_runtime.jsx)("p", {
						className: "text-lg font-semibold leading-tight",
						children: t.name
					}), /* @__PURE__ */ (0, import_jsx_runtime.jsx)("p", {
						className: "text-muted text-sm",
						children: t.tagline
					})] })]
				}), /* @__PURE__ */ (0, import_jsx_runtime.jsxs)("div", {
					className: "flex items-center gap-2",
					children: [
						/* @__PURE__ */ (0, import_jsx_runtime.jsx)("button", {
							type: "button",
							className: "border-border bg-surface size-11 rounded-md border",
							"aria-label": t.language,
							onClick: () => switchLocale(locale === "ko" ? "en" : "ko"),
							children: /* @__PURE__ */ (0, import_jsx_runtime.jsx)(Languages, { className: "mx-auto size-5" })
						}),
						/* @__PURE__ */ (0, import_jsx_runtime.jsx)("button", {
							type: "button",
							className: "border-border bg-surface size-11 rounded-md border",
							"aria-label": t.theme,
							onClick: () => cycleTheme(),
							children: theme === "dark" ? /* @__PURE__ */ (0, import_jsx_runtime.jsx)(Moon, { className: "mx-auto size-5" }) : /* @__PURE__ */ (0, import_jsx_runtime.jsx)(Sun, { className: "mx-auto size-5" })
						}),
						gate === "ready" ? /* @__PURE__ */ (0, import_jsx_runtime.jsx)("button", {
							type: "button",
							className: "border-border bg-surface hidden h-11 rounded-md border px-3 text-sm sm:inline",
							onClick: () => void logout(),
							children: t.logout
						}) : null
					]
				})]
			}),
			/* @__PURE__ */ (0, import_jsx_runtime.jsxs)("p", {
				className: "border-border bg-surface text-muted rounded-md border px-4 py-3 text-sm leading-relaxed",
				children: [
					t.notice,
					" ",
					/* @__PURE__ */ (0, import_jsx_runtime.jsx)("a", {
						className: "text-fg underline",
						href: "https://www.youtube.com/static?template=terms",
						children: t.terms
					}),
					" · ",
					/* @__PURE__ */ (0, import_jsx_runtime.jsx)("a", {
						className: "text-fg underline",
						href: "https://support.google.com/youtube/answer/56100?hl=en",
						children: t.ownUploads
					})
				]
			}),
			settings?.capabilities.demo_data ? /* @__PURE__ */ (0, import_jsx_runtime.jsx)("p", {
				className: "bg-warn text-primary-fg rounded-md px-4 py-2 text-sm font-medium",
				children: t.demo
			}) : null,
			gate === "boot" ? /* @__PURE__ */ (0, import_jsx_runtime.jsx)("p", {
				className: "text-muted",
				children: t.checking
			}) : null,
			gate === "offline" ? /* @__PURE__ */ (0, import_jsx_runtime.jsxs)("section", {
				className: "border-border bg-surface rounded-md border p-5",
				role: "status",
				children: [/* @__PURE__ */ (0, import_jsx_runtime.jsx)("h1", {
					className: "text-xl font-semibold",
					children: t.offlineTitle
				}), /* @__PURE__ */ (0, import_jsx_runtime.jsx)("p", {
					className: "text-muted mt-2 text-sm leading-relaxed",
					children: t.offlineBody
				})]
			}) : null,
			gate === "setup" || gate === "login" ? /* @__PURE__ */ (0, import_jsx_runtime.jsxs)("form", {
				className: "border-border bg-surface grid gap-3 rounded-md border p-5",
				onSubmit: gate === "setup" ? onSetup : onLogin,
				children: [
					/* @__PURE__ */ (0, import_jsx_runtime.jsx)("h1", {
						className: "text-xl font-semibold",
						children: gate === "setup" ? t.setupTitle : t.loginTitle
					}),
					/* @__PURE__ */ (0, import_jsx_runtime.jsx)("p", {
						className: "text-muted text-sm",
						children: gate === "setup" ? t.setupBody : null
					}),
					/* @__PURE__ */ (0, import_jsx_runtime.jsxs)("label", {
						className: "grid gap-1 text-sm",
						children: [t.password, /* @__PURE__ */ (0, import_jsx_runtime.jsx)("input", {
							className: "border-border bg-bg h-11 rounded-md border px-3",
							type: "password",
							autoComplete: "new-password",
							value: password,
							onChange: (event) => setPassword(event.target.value),
							required: true,
							minLength: 10
						})]
					}),
					gate === "setup" ? /* @__PURE__ */ (0, import_jsx_runtime.jsxs)("label", {
						className: "grid gap-1 text-sm",
						children: [t.confirm, /* @__PURE__ */ (0, import_jsx_runtime.jsx)("input", {
							className: "border-border bg-bg h-11 rounded-md border px-3",
							type: "password",
							autoComplete: "new-password",
							value: confirm,
							onChange: (event) => setConfirm(event.target.value),
							required: true,
							minLength: 10
						})]
					}) : null,
					formError ? /* @__PURE__ */ (0, import_jsx_runtime.jsx)("p", {
						className: "text-danger text-sm",
						role: "alert",
						children: formError
					}) : null,
					/* @__PURE__ */ (0, import_jsx_runtime.jsx)("button", {
						className: "bg-primary text-primary-fg h-11 rounded-md font-medium",
						type: "submit",
						disabled: busy,
						children: gate === "setup" ? t.savePassword : t.login
					})
				]
			}) : null,
			gate === "ready" ? /* @__PURE__ */ (0, import_jsx_runtime.jsxs)(import_jsx_runtime.Fragment, { children: [
				/* @__PURE__ */ (0, import_jsx_runtime.jsxs)("form", {
					className: "grid gap-3",
					onSubmit: onAnalyze,
					children: [
						/* @__PURE__ */ (0, import_jsx_runtime.jsxs)("label", {
							className: "grid gap-2 text-sm font-medium",
							htmlFor: "video-url",
							children: [t.urlLabel, /* @__PURE__ */ (0, import_jsx_runtime.jsx)("input", {
								id: "video-url",
								className: "border-border bg-surface h-12 rounded-md border px-3 text-base",
								value: url,
								onChange: (event) => setUrl(event.target.value),
								placeholder: "https://www.youtube.com/watch?v=",
								inputMode: "url",
								autoCapitalize: "off",
								autoCorrect: "off",
								spellCheck: false,
								required: true
							})]
						}),
						/* @__PURE__ */ (0, import_jsx_runtime.jsx)("p", {
							className: "text-muted text-sm",
							children: t.urlHint
						}),
						urlError ? /* @__PURE__ */ (0, import_jsx_runtime.jsx)("p", {
							className: "text-danger text-sm",
							role: "alert",
							children: urlError
						}) : null,
						parentId ? /* @__PURE__ */ (0, import_jsx_runtime.jsxs)("p", {
							className: "border-border bg-surface flex items-center justify-between gap-3 rounded-md border px-3 py-2 text-sm",
							children: [/* @__PURE__ */ (0, import_jsx_runtime.jsx)("span", { children: t.retryHint }), /* @__PURE__ */ (0, import_jsx_runtime.jsx)("button", {
								type: "button",
								className: "underline",
								onClick: () => setParentId(null),
								children: t.clearRetry
							})]
						}) : null,
						/* @__PURE__ */ (0, import_jsx_runtime.jsxs)("div", {
							className: "flex gap-2",
							children: [/* @__PURE__ */ (0, import_jsx_runtime.jsx)("button", {
								className: "bg-primary text-primary-fg h-11 flex-1 rounded-md font-medium",
								type: "submit",
								disabled: busy,
								children: busy ? t.creating : t.analyze
							}), /* @__PURE__ */ (0, import_jsx_runtime.jsx)("button", {
								className: "border-border bg-surface h-11 rounded-md border px-3",
								type: "button",
								"aria-label": t.paste,
								onClick: () => {
									navigator.clipboard?.readText().then((text) => setUrl(text)).catch(() => void 0);
								},
								children: /* @__PURE__ */ (0, import_jsx_runtime.jsx)(ClipboardPaste, { className: "size-5" })
							})]
						})
					]
				}),
				analysis ? /* @__PURE__ */ (0, import_jsx_runtime.jsxs)("section", {
					className: "border-border bg-surface grid gap-4 rounded-md border p-4",
					"aria-label": t.metadata,
					children: [
						/* @__PURE__ */ (0, import_jsx_runtime.jsxs)("div", {
							className: "flex gap-4",
							children: [/* @__PURE__ */ (0, import_jsx_runtime.jsx)("div", {
								className: "bg-bg grid h-24 w-40 shrink-0 place-items-center overflow-hidden rounded-md",
								children: analysis.source.thumbnail_url ? /* @__PURE__ */ (0, import_jsx_runtime.jsx)("img", {
									src: analysis.source.thumbnail_url,
									alt: "",
									className: "h-full w-full object-cover"
								}) : /* @__PURE__ */ (0, import_jsx_runtime.jsx)("span", {
									className: "text-muted px-2 text-center text-xs",
									children: t.noThumb
								})
							}), /* @__PURE__ */ (0, import_jsx_runtime.jsxs)("div", {
								className: "min-w-0",
								children: [
									/* @__PURE__ */ (0, import_jsx_runtime.jsx)("h2", {
										className: "text-lg font-semibold leading-snug",
										children: analysis.source.title
									}),
									/* @__PURE__ */ (0, import_jsx_runtime.jsx)("p", {
										className: "text-muted mt-1 text-sm",
										children: analysis.source.channel
									}),
									/* @__PURE__ */ (0, import_jsx_runtime.jsx)("p", {
										className: "mt-1 text-sm",
										children: formatDuration(analysis.source.duration_seconds)
									}),
									/* @__PURE__ */ (0, import_jsx_runtime.jsx)("a", {
										className: "mt-1 inline-block text-sm underline",
										href: analysis.source.canonical_url,
										children: t.source
									})
								]
							})]
						}),
						analysis.source.ignored_timestamp ? /* @__PURE__ */ (0, import_jsx_runtime.jsx)("p", {
							className: "text-muted text-sm",
							children: t.timestamp
						}) : null,
						analysis.source.ignored_playlist ? /* @__PURE__ */ (0, import_jsx_runtime.jsx)("p", {
							className: "text-muted text-sm",
							children: t.playlistIgnored
						}) : null,
						/* @__PURE__ */ (0, import_jsx_runtime.jsx)("div", {
							className: "grid grid-cols-3 gap-2",
							role: "tablist",
							children: [
								"mp4",
								"mp3",
								"original_audio"
							].map((kind) => /* @__PURE__ */ (0, import_jsx_runtime.jsx)("button", {
								type: "button",
								role: "tab",
								"aria-selected": tab === kind,
								className: `h-11 rounded-md border text-sm ${tab === kind ? "bg-primary text-primary-fg border-primary" : "border-border bg-bg"}`,
								onClick: () => {
									setTab(kind);
									const next = analysis.choices.find((item) => item.kind === kind && item.is_default) || analysis.choices.find((item) => item.kind === kind);
									setChoiceId(next?.choice_id || null);
									setConsent(false);
								},
								children: kind === "mp4" ? t.tabMp4 : kind === "mp3" ? t.tabMp3 : t.tabOriginal
							}, kind))
						}),
						choices.length === 0 ? /* @__PURE__ */ (0, import_jsx_runtime.jsx)("p", {
							className: "text-muted text-sm",
							children: t.noChoice
						}) : null,
						/* @__PURE__ */ (0, import_jsx_runtime.jsx)("div", {
							className: "grid gap-2",
							role: "radiogroup",
							"aria-label": t.confirmLabel,
							children: choices.map((choice) => /* @__PURE__ */ (0, import_jsx_runtime.jsxs)("label", {
								className: "border-border bg-bg grid gap-1 rounded-md border px-3 py-3 text-sm",
								children: [/* @__PURE__ */ (0, import_jsx_runtime.jsxs)("span", {
									className: "flex items-center gap-2 font-medium",
									children: [
										/* @__PURE__ */ (0, import_jsx_runtime.jsx)("input", {
											type: "radio",
											name: "choice",
											checked: choiceId === choice.choice_id,
											onChange: () => {
												setChoiceId(choice.choice_id);
												setConsent(false);
											}
										}),
										choice.label,
										choice.portrait ? /* @__PURE__ */ (0, import_jsx_runtime.jsx)("span", {
											className: "text-muted font-normal",
											children: t.portrait
										}) : null
									]
								}), /* @__PURE__ */ (0, import_jsx_runtime.jsxs)("span", {
									className: "text-muted",
									children: [
										[
											choice.resolution_label,
											choice.width && choice.height ? `${choice.width}×${choice.height}` : null,
											choice.vcodec,
											choice.acodec,
											choice.fps ? `${choice.fps} fps` : null
										].filter(Boolean).join(" · "),
										choice.audio_language ? ` · ${choice.audio_language}` : "",
										choice.audio_role ? ` · ${t.role[choice.audio_role] || choice.audio_role}` : "",
										choice.estimated_bytes != null ? ` · ${choice.size_is_estimate ? t.estimate + " " : ""}${formatBytes(choice.estimated_bytes)}` : ""
									]
								})]
							}, choice.choice_id))
						}),
						/* @__PURE__ */ (0, import_jsx_runtime.jsxs)("details", {
							className: "text-sm",
							children: [/* @__PURE__ */ (0, import_jsx_runtime.jsx)("summary", {
								className: "cursor-pointer",
								children: t.details
							}), /* @__PURE__ */ (0, import_jsx_runtime.jsx)("p", {
								className: "text-muted mt-2 leading-relaxed",
								children: tab === "mp3" ? t.bitrateNote : tab === "original_audio" ? t.originalNote : t.conversionNote
							})]
						}),
						selected ? /* @__PURE__ */ (0, import_jsx_runtime.jsxs)("p", {
							className: "text-sm",
							children: [
								/* @__PURE__ */ (0, import_jsx_runtime.jsxs)("span", {
									className: "font-medium",
									children: [t.confirmLabel, ": "]
								}),
								selected.label,
								". ",
								selected.conversion_required || selected.kind === "mp3" ? t.convert : t.copy
							]
						}) : null,
						selected?.requires_consent ? /* @__PURE__ */ (0, import_jsx_runtime.jsxs)("label", {
							className: "flex items-start gap-2 text-sm",
							children: [/* @__PURE__ */ (0, import_jsx_runtime.jsx)("input", {
								type: "checkbox",
								className: "mt-1",
								checked: consent,
								onChange: (event) => setConsent(event.target.checked)
							}), t.consent]
						}) : null,
						/* @__PURE__ */ (0, import_jsx_runtime.jsxs)("label", {
							className: "flex items-start gap-2 text-sm",
							children: [/* @__PURE__ */ (0, import_jsx_runtime.jsx)("input", {
								type: "checkbox",
								className: "mt-1",
								checked: keep,
								onChange: (event) => setKeep(event.target.checked)
							}), /* @__PURE__ */ (0, import_jsx_runtime.jsxs)("span", { children: [
								t.keep,
								/* @__PURE__ */ (0, import_jsx_runtime.jsx)("span", {
									className: "text-muted block",
									children: t.keepHint
								}),
								settings ? /* @__PURE__ */ (0, import_jsx_runtime.jsxs)("span", {
									className: "text-muted block",
									children: [
										t.quota,
										": ",
										formatBytes(settings.capabilities.storage_used_bytes),
										" / ",
										formatBytes(settings.capabilities.storage_limit_bytes)
									]
								}) : null
							] })]
						}),
						/* @__PURE__ */ (0, import_jsx_runtime.jsx)("button", {
							className: "bg-primary text-primary-fg h-11 rounded-md font-medium",
							type: "button",
							disabled: !selected || busy || selected.requires_consent && !consent,
							onClick: () => void onCreate(),
							children: t.create
						})
					]
				}) : null,
				/* @__PURE__ */ (0, import_jsx_runtime.jsxs)("section", {
					className: "grid gap-3",
					"aria-live": "polite",
					children: [/* @__PURE__ */ (0, import_jsx_runtime.jsxs)("div", {
						className: "flex items-center justify-between",
						children: [/* @__PURE__ */ (0, import_jsx_runtime.jsx)("h2", {
							className: "text-lg font-semibold",
							children: t.jobs
						}), /* @__PURE__ */ (0, import_jsx_runtime.jsx)("span", {
							className: "text-muted text-xs",
							children: live === "live" ? t.live : t.polling
						})]
					}), active.length === 0 ? /* @__PURE__ */ (0, import_jsx_runtime.jsx)("p", {
						className: "text-muted text-sm",
						children: t.emptyJobs
					}) : active.map((job) => /* @__PURE__ */ (0, import_jsx_runtime.jsx)(JobCard, {
						job,
						locale,
						onChange: () => void refreshJobs(),
						csrf,
						onRetry: beginRetry
					}, job.id))]
				}),
				/* @__PURE__ */ (0, import_jsx_runtime.jsxs)("section", {
					className: "grid gap-3",
					children: [/* @__PURE__ */ (0, import_jsx_runtime.jsx)("h2", {
						className: "text-lg font-semibold",
						children: t.history
					}), history.length === 0 ? /* @__PURE__ */ (0, import_jsx_runtime.jsx)("p", {
						className: "text-muted text-sm",
						children: t.emptyHistory
					}) : history.map((job) => /* @__PURE__ */ (0, import_jsx_runtime.jsx)(JobCard, {
						job,
						locale,
						onChange: () => void refreshJobs(),
						csrf,
						onRetry: beginRetry
					}, job.id))]
				}),
				settings?.capabilities.playlists_enabled ? /* @__PURE__ */ (0, import_jsx_runtime.jsxs)("section", {
					className: "border-border bg-surface grid gap-3 rounded-md border p-4",
					children: [
						/* @__PURE__ */ (0, import_jsx_runtime.jsx)("h2", {
							className: "text-lg font-semibold",
							children: t.playlistTitle
						}),
						/* @__PURE__ */ (0, import_jsx_runtime.jsx)("p", {
							className: "text-muted text-sm leading-relaxed",
							children: t.playlistHint
						}),
						/* @__PURE__ */ (0, import_jsx_runtime.jsxs)("form", {
							className: "flex gap-2",
							onSubmit: (event) => {
								event.preventDefault();
								setPlaylistError(null);
								setBusy(true);
								api.playlist(csrf, locale, playlistUrl.trim()).then(setPlaylist).catch((error) => setPlaylistError(messageOf(error))).finally(() => setBusy(false));
							},
							children: [/* @__PURE__ */ (0, import_jsx_runtime.jsx)("input", {
								className: "border-border bg-bg h-11 flex-1 rounded-md border px-3",
								value: playlistUrl,
								onChange: (event) => setPlaylistUrl(event.target.value),
								placeholder: "https://www.youtube.com/playlist?list=",
								"aria-label": t.playlistTitle
							}), /* @__PURE__ */ (0, import_jsx_runtime.jsx)("button", {
								className: "bg-primary text-primary-fg h-11 rounded-md px-3 text-sm",
								type: "submit",
								disabled: busy,
								children: t.analyze
							})]
						}),
						playlistError ? /* @__PURE__ */ (0, import_jsx_runtime.jsx)("p", {
							className: "text-danger text-sm",
							role: "alert",
							children: playlistError
						}) : null,
						playlist?.limited ? /* @__PURE__ */ (0, import_jsx_runtime.jsx)("p", {
							className: "text-muted text-sm",
							children: t.playlistLimited
						}) : null,
						/* @__PURE__ */ (0, import_jsx_runtime.jsx)("ul", {
							className: "grid gap-2",
							children: playlist?.entries.map((entry) => /* @__PURE__ */ (0, import_jsx_runtime.jsxs)("li", {
								className: "border-border bg-bg flex items-center justify-between gap-3 rounded-md border px-3 py-2 text-sm",
								children: [/* @__PURE__ */ (0, import_jsx_runtime.jsxs)("span", {
									className: "min-w-0",
									children: [
										/* @__PURE__ */ (0, import_jsx_runtime.jsx)("span", {
											className: "text-muted mr-2",
											children: entry.position
										}),
										entry.title || t.unknown,
										!entry.available ? /* @__PURE__ */ (0, import_jsx_runtime.jsx)("span", {
											className: "text-danger ml-2",
											children: entry.reason || t.playlistUnavailable
										}) : null
									]
								}), entry.available && entry.canonical_url ? /* @__PURE__ */ (0, import_jsx_runtime.jsx)("button", {
									type: "button",
									className: "shrink-0 underline",
									onClick: () => {
										setUrl(entry.canonical_url || "");
										setParentId(null);
										setAnalysis(null);
									},
									children: t.playlistUse
								}) : null]
							}, entry.position))
						})
					]
				}) : null,
				/* @__PURE__ */ (0, import_jsx_runtime.jsx)("button", {
					type: "button",
					className: "text-muted text-left text-sm underline",
					onClick: () => void showDiag(),
					children: t.diagnostics
				}),
				diag ? /* @__PURE__ */ (0, import_jsx_runtime.jsx)("pre", {
					className: "border-border bg-surface overflow-auto rounded-md border p-3 text-xs",
					children: diag
				}) : null
			] }) : null
		]
	});
	function switchLocale(next) {
		setLocale(next);
		if (csrf) api.patchSettings(csrf, { language: next }).then(setSettings).catch(() => void 0);
	}
	function cycleTheme() {
		const order = [
			"system",
			"light",
			"dark"
		];
		const next = order[(order.indexOf(theme) + 1) % order.length];
		setTheme(next);
		applyTheme(next);
		if (csrf) api.patchSettings(csrf, { theme: next }).catch(() => void 0);
	}
	function beginRetry(job) {
		setParentId(job.id);
		setUrl(job.source.canonical_url || "");
		setAnalysis(null);
		setUrlError(null);
	}
	async function logout() {
		if (!csrf) return;
		await api.logout(csrf);
		setSession({
			authenticated: false,
			bootstrapped: true
		});
		setGate("login");
	}
	async function showDiag() {
		if (!csrf) return;
		const value = await api.diagnostics(csrf);
		setDiag(JSON.stringify(value, null, 2));
	}
}
function JobCard({ job, locale, csrf, onChange, onRetry }) {
	const t = translate(locale);
	const percent = job.progress?.percent;
	const known = typeof percent === "number" && job.progress?.total_bytes != null && !job.progress.total_is_estimate;
	return /* @__PURE__ */ (0, import_jsx_runtime.jsxs)("article", {
		className: "border-border bg-surface grid gap-2 rounded-md border p-4",
		children: [
			/* @__PURE__ */ (0, import_jsx_runtime.jsxs)("div", {
				className: "flex items-start justify-between gap-3",
				children: [/* @__PURE__ */ (0, import_jsx_runtime.jsxs)("div", { children: [/* @__PURE__ */ (0, import_jsx_runtime.jsx)("h3", {
					className: "font-medium",
					children: job.source.title || job.output.label
				}), /* @__PURE__ */ (0, import_jsx_runtime.jsxs)("p", {
					className: "text-muted text-sm",
					children: [
						t.status[job.status],
						job.phase ? ` · ${t.phase[job.phase] || job.phase}` : "",
						job.queue_position ? ` · ${t.queue} ${job.queue_position}` : ""
					]
				})] }), /* @__PURE__ */ (0, import_jsx_runtime.jsx)("p", {
					className: "text-muted text-xs",
					children: new Date(job.updated_at).toLocaleString(locale === "ko" ? "ko-KR" : "en")
				})]
			}),
			job.status === "running" || job.status === "queued" ? /* @__PURE__ */ (0, import_jsx_runtime.jsx)("div", {
				className: "bg-bg h-2 overflow-hidden rounded-full",
				role: "progressbar",
				"aria-valuemin": 0,
				"aria-valuemax": 100,
				"aria-valuenow": known ? Math.round(percent || 0) : void 0,
				"aria-label": job.phase || job.status,
				children: /* @__PURE__ */ (0, import_jsx_runtime.jsx)("div", {
					className: known ? "bg-primary h-full" : "indeterminate h-full",
					style: known ? { width: `${percent}%` } : void 0
				})
			}) : null,
			job.progress && (job.status === "running" || job.status === "queued") ? /* @__PURE__ */ (0, import_jsx_runtime.jsxs)("p", {
				className: "text-muted text-xs",
				children: [
					job.progress.total_bytes == null ? t.unknownProgress : null,
					job.progress.speed_bps != null ? ` ${t.speed} ${formatBytes(job.progress.speed_bps)}/s` : "",
					job.progress.eta_seconds != null ? ` · ${t.eta} ${formatDuration(job.progress.eta_seconds)}` : ""
				]
			}) : null,
			job.cancel_requested && job.status === "running" ? /* @__PURE__ */ (0, import_jsx_runtime.jsx)("p", {
				className: "text-sm",
				children: t.cancelling
			}) : null,
			job.error ? /* @__PURE__ */ (0, import_jsx_runtime.jsxs)("p", {
				className: "text-danger text-sm",
				role: "alert",
				children: [
					job.error.message,
					" ",
					job.error.action
				]
			}) : null,
			/* @__PURE__ */ (0, import_jsx_runtime.jsxs)("p", {
				className: "text-muted text-xs",
				children: [
					t.fileState[job.file_state],
					job.artifact ? ` · ${formatBytes(job.artifact.bytes)} · ${job.keep_on_server ? t.stored : job.artifact.expires_at ? new Date(job.artifact.expires_at).toLocaleString(locale === "ko" ? "ko-KR" : "en") : ""}` : "",
					job.file_state === "available" ? ` · ${t.folder}: ${t.logicalFolder}` : ""
				]
			}),
			/* @__PURE__ */ (0, import_jsx_runtime.jsxs)("div", {
				className: "flex flex-wrap gap-2",
				children: [
					job.file_state === "available" ? /* @__PURE__ */ (0, import_jsx_runtime.jsxs)("a", {
						className: "bg-primary text-primary-fg inline-flex h-11 items-center gap-2 rounded-md px-3 text-sm",
						href: `/api/v1/jobs/${job.id}/file`,
						children: [
							/* @__PURE__ */ (0, import_jsx_runtime.jsx)(Download, { className: "size-4" }),
							" ",
							t.download
						]
					}) : null,
					job.status === "queued" || job.status === "running" ? /* @__PURE__ */ (0, import_jsx_runtime.jsx)("button", {
						type: "button",
						className: "border-border h-11 rounded-md border px-3 text-sm",
						onClick: () => void api.cancel(csrf, job.id).then(onChange),
						children: t.cancel
					}) : null,
					job.file_state === "available" ? /* @__PURE__ */ (0, import_jsx_runtime.jsx)("button", {
						type: "button",
						className: "border-border h-11 rounded-md border px-3 text-sm",
						onClick: () => void api.retention(csrf, job.id, !job.keep_on_server).then(onChange),
						children: job.keep_on_server ? t.expire : t.keep
					}) : null,
					job.file_state === "available" ? /* @__PURE__ */ (0, import_jsx_runtime.jsx)("button", {
						type: "button",
						className: "border-border h-11 rounded-md border px-3 text-sm",
						onClick: () => void api.deleteFile(csrf, job.id).then(onChange),
						children: t.deleteFile
					}) : null,
					job.status !== "queued" && job.status !== "running" ? /* @__PURE__ */ (0, import_jsx_runtime.jsx)("button", {
						type: "button",
						className: "border-border h-11 rounded-md border px-3 text-sm",
						onClick: () => onRetry(job),
						children: t.retry
					}) : null,
					job.file_state !== "available" && job.status !== "queued" && job.status !== "running" ? /* @__PURE__ */ (0, import_jsx_runtime.jsx)("button", {
						type: "button",
						className: "border-border h-11 rounded-md border px-3 text-sm",
						onClick: () => void api.deleteHistory(csrf, job.id).then(onChange),
						children: t.deleteHistory
					}) : null
				]
			}),
			job.status === "running" ? /* @__PURE__ */ (0, import_jsx_runtime.jsx)(LoaderCircle, {
				className: "text-muted size-4 animate-spin",
				"aria-hidden": "true"
			}) : null
		]
	});
}
function messageOf(error) {
	if (error && typeof error === "object" && "body" in error) {
		const body = error.body;
		if (body?.error?.message) return `${body.error.message} ${body.error.action || ""}`.trim();
	}
	if (error instanceof Error) return error.message;
	return "Error";
}
function Home() {
	return /* @__PURE__ */ (0, import_jsx_runtime.jsx)(DownloaderApp, {});
}
//#endregion
export { Home as component };
