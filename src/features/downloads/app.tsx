import { useEffect, useMemo, useState } from "react";
import { Archive, ClipboardPaste, Download, Languages, LoaderCircle, Moon, Sun } from "lucide-react";
import { api, type Analysis, type Choice, type Job, type PlaylistInspection, type Session, type Settings } from "./api";
import { translate, type Locale } from "./i18n";

type Gate = "boot" | "offline" | "setup" | "login" | "ready";

function formatDuration(seconds: number | null | undefined): string {
  if (seconds == null || Number.isNaN(seconds)) return "—";
  const total = Math.round(seconds);
  const h = Math.floor(total / 3600);
  const m = Math.floor((total % 3600) / 60);
  const s = total % 60;
  if (h) return `${h}:${String(m).padStart(2, "0")}:${String(s).padStart(2, "0")}`;
  return `${m}:${String(s).padStart(2, "0")}`;
}

function formatBytes(value: number | null | undefined): string {
  if (value == null) return "—";
  const units = ["B", "KB", "MB", "GB"];
  let n = value;
  let i = 0;
  while (n >= 1024 && i < units.length - 1) {
    n /= 1024;
    i += 1;
  }
  return `${n.toFixed(n >= 10 || i === 0 ? 0 : 1)} ${units[i]}`;
}

function applyTheme(theme: "light" | "dark" | "system") {
  const dark = theme === "dark" || (theme === "system" && window.matchMedia("(prefers-color-scheme: dark)").matches);
  document.documentElement.dataset.theme = dark ? "dark" : "light";
  localStorage.setItem("seorap-theme", theme);
}

export function DownloaderApp() {
  const [locale, setLocale] = useState<Locale>("ko");
  const t = translate(locale);
  const [gate, setGate] = useState<Gate>("boot");
  const [session, setSession] = useState<Session | null>(null);
  const [settings, setSettings] = useState<Settings | null>(null);
  const [password, setPassword] = useState("");
  const [confirm, setConfirm] = useState("");
  const [formError, setFormError] = useState<string | null>(null);
  const [url, setUrl] = useState("");
  const [urlError, setUrlError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const [analysis, setAnalysis] = useState<Analysis | null>(null);
  const [tab, setTab] = useState<Choice["kind"]>("mp4");
  const [choiceId, setChoiceId] = useState<string | null>(null);
  const [keep, setKeep] = useState(false);
  const [consent, setConsent] = useState(false);
  const [jobs, setJobs] = useState<Job[]>([]);
  const [parentId, setParentId] = useState<string | null>(null);
  const [playlistUrl, setPlaylistUrl] = useState("");
  const [playlist, setPlaylist] = useState<PlaylistInspection | null>(null);
  const [playlistError, setPlaylistError] = useState<string | null>(null);
  const [live, setLive] = useState<"live" | "polling">("polling");
  const [diag, setDiag] = useState<string | null>(null);
  const [theme, setTheme] = useState<"light" | "dark" | "system">("system");

  const csrf = session && session.authenticated ? session.csrf_token : "";

  useEffect(() => {
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

  useEffect(() => {
    document.documentElement.lang = locale;
    localStorage.setItem("seorap-lang", locale);
  }, [locale]);

  useEffect(() => {
    if (gate !== "ready" || !csrf) return;
    api.settings(csrf).then((value) => {
      setSettings(value);
      setLocale(value.language);
      setTheme(value.theme);
      applyTheme(value.theme);
    }).catch(() => undefined);
    refreshJobs(csrf);
  }, [gate, csrf]);

  useEffect(() => {
    if (theme) applyTheme(theme);
  }, [theme]);

  const active = jobs.filter((job) => job.status === "queued" || job.status === "running");
  const history = jobs.filter((job) => job.status !== "queued" && job.status !== "running");

  async function refreshJobs(token = csrf) {
    if (!token) return;
    const list = await api.jobs(token);
    setJobs(list.jobs);
  }

  async function onSetup(event: React.FormEvent) {
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

  async function onLogin(event: React.FormEvent) {
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

  async function onAnalyze(event: React.FormEvent) {
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
        conversion_consent: consent,
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

  function watch(id: string) {
    const source = new EventSource(`/api/v1/jobs/${id}/events`);
    setLive("live");
    source.addEventListener("snapshot", (event) => {
      const job = JSON.parse((event as MessageEvent).data) as Job;
      setJobs((current) => [job, ...current.filter((item) => item.id !== job.id)]);
      if (["succeeded", "failed", "cancelled", "interrupted"].includes(job.status)) source.close();
    });
    source.onerror = () => {
      source.close();
      setLive("polling");
      api.job(csrf, id).then((job) => {
        setJobs((current) => [job, ...current.filter((item) => item.id !== job.id)]);
      }).catch(() => undefined);
    };
  }

  const choices = useMemo(() => analysis?.choices.filter((item) => item.kind === tab) || [], [analysis, tab]);
  const selected = analysis?.choices.find((item) => item.choice_id === choiceId) || null;

  return (
    <main className="mx-auto flex min-h-screen w-full max-w-3xl flex-col gap-6 px-4 py-6 sm:px-6">
      <header className="flex items-center justify-between gap-3">
        <div className="flex items-center gap-3">
          <span className="bg-primary text-primary-fg grid size-11 place-items-center rounded-md" aria-hidden="true">
            <Archive className="size-5" />
          </span>
          <div>
            <p className="text-lg font-semibold leading-tight">{t.name}</p>
            <p className="text-muted text-sm">{t.tagline}</p>
          </div>
        </div>
        <div className="flex items-center gap-2">
          <button type="button" className="border-border bg-surface size-11 rounded-md border" aria-label={t.language} onClick={() => switchLocale(locale === "ko" ? "en" : "ko")}>
            <Languages className="mx-auto size-5" />
          </button>
          <button type="button" className="border-border bg-surface size-11 rounded-md border" aria-label={t.theme} onClick={() => cycleTheme()}>
            {theme === "dark" ? <Moon className="mx-auto size-5" /> : <Sun className="mx-auto size-5" />}
          </button>
          {gate === "ready" ? (
            <button type="button" className="border-border bg-surface hidden h-11 rounded-md border px-3 text-sm sm:inline" onClick={() => void logout()}>
              {t.logout}
            </button>
          ) : null}
        </div>
      </header>

      <p className="border-border bg-surface text-muted rounded-md border px-4 py-3 text-sm leading-relaxed">
        {t.notice}{" "}
        <a className="text-fg underline" href="https://www.youtube.com/static?template=terms">
          {t.terms}
        </a>
        {" · "}
        <a className="text-fg underline" href="https://support.google.com/youtube/answer/56100?hl=en">
          {t.ownUploads}
        </a>
      </p>

      {settings?.capabilities.demo_data ? (
        <p className="bg-warn text-primary-fg rounded-md px-4 py-2 text-sm font-medium">{t.demo}</p>
      ) : null}

      {gate === "boot" ? <p className="text-muted">{t.checking}</p> : null}
      {gate === "offline" ? (
        <section className="border-border bg-surface rounded-md border p-5" role="status">
          <h1 className="text-xl font-semibold">{t.offlineTitle}</h1>
          <p className="text-muted mt-2 text-sm leading-relaxed">{t.offlineBody}</p>
        </section>
      ) : null}
      {gate === "setup" || gate === "login" ? (
        <form className="border-border bg-surface grid gap-3 rounded-md border p-5" onSubmit={gate === "setup" ? onSetup : onLogin}>
          <h1 className="text-xl font-semibold">{gate === "setup" ? t.setupTitle : t.loginTitle}</h1>
          <p className="text-muted text-sm">{gate === "setup" ? t.setupBody : null}</p>
          <label className="grid gap-1 text-sm">
            {t.password}
            <input className="border-border bg-bg h-11 rounded-md border px-3" type="password" autoComplete="new-password" value={password} onChange={(event) => setPassword(event.target.value)} required minLength={10} />
          </label>
          {gate === "setup" ? (
            <label className="grid gap-1 text-sm">
              {t.confirm}
              <input className="border-border bg-bg h-11 rounded-md border px-3" type="password" autoComplete="new-password" value={confirm} onChange={(event) => setConfirm(event.target.value)} required minLength={10} />
            </label>
          ) : null}
          {formError ? <p className="text-danger text-sm" role="alert">{formError}</p> : null}
          <button className="bg-primary text-primary-fg h-11 rounded-md font-medium" type="submit" disabled={busy}>
            {gate === "setup" ? t.savePassword : t.login}
          </button>
        </form>
      ) : null}

      {gate === "ready" ? (
        <>
          <form className="grid gap-3" onSubmit={onAnalyze}>
            <label className="grid gap-2 text-sm font-medium" htmlFor="video-url">
              {t.urlLabel}
              <input
                id="video-url"
                className="border-border bg-surface h-12 rounded-md border px-3 text-base"
                value={url}
                onChange={(event) => setUrl(event.target.value)}
                placeholder="https://www.youtube.com/watch?v="
                inputMode="url"
                autoCapitalize="off"
                autoCorrect="off"
                spellCheck={false}
                required
              />
            </label>
            <p className="text-muted text-sm">{t.urlHint}</p>
            {urlError ? <p className="text-danger text-sm" role="alert">{urlError}</p> : null}
            {parentId ? (
              <p className="border-border bg-surface flex items-center justify-between gap-3 rounded-md border px-3 py-2 text-sm">
                <span>{t.retryHint}</span>
                <button type="button" className="underline" onClick={() => setParentId(null)}>
                  {t.clearRetry}
                </button>
              </p>
            ) : null}
            <div className="flex gap-2">
              <button className="bg-primary text-primary-fg h-11 flex-1 rounded-md font-medium" type="submit" disabled={busy}>
                {busy ? t.creating : t.analyze}
              </button>
              <button
                className="border-border bg-surface h-11 rounded-md border px-3"
                type="button"
                aria-label={t.paste}
                onClick={() => {
                  navigator.clipboard?.readText().then((text) => setUrl(text)).catch(() => undefined);
                }}
              >
                <ClipboardPaste className="size-5" />
              </button>
            </div>
          </form>

          {analysis ? (
            <section className="border-border bg-surface grid gap-4 rounded-md border p-4" aria-label={t.metadata}>
              <div className="flex gap-4">
                <div className="bg-bg grid h-24 w-40 shrink-0 place-items-center overflow-hidden rounded-md">
                  {analysis.source.thumbnail_url ? (
                    <img src={analysis.source.thumbnail_url} alt="" className="h-full w-full object-cover" />
                  ) : (
                    <span className="text-muted px-2 text-center text-xs">{t.noThumb}</span>
                  )}
                </div>
                <div className="min-w-0">
                  <h2 className="text-lg font-semibold leading-snug">{analysis.source.title}</h2>
                  <p className="text-muted mt-1 text-sm">{analysis.source.channel}</p>
                  <p className="mt-1 text-sm">{formatDuration(analysis.source.duration_seconds)}</p>
                  <a className="mt-1 inline-block text-sm underline" href={analysis.source.canonical_url}>
                    {t.source}
                  </a>
                </div>
              </div>
              {analysis.source.ignored_timestamp ? <p className="text-muted text-sm">{t.timestamp}</p> : null}
              {analysis.source.ignored_playlist ? <p className="text-muted text-sm">{t.playlistIgnored}</p> : null}
              <div className="grid grid-cols-3 gap-2" role="tablist">
                {(["mp4", "mp3", "original_audio"] as const).map((kind) => (
                  <button
                    key={kind}
                    type="button"
                    role="tab"
                    aria-selected={tab === kind}
                    className={`h-11 rounded-md border text-sm ${tab === kind ? "bg-primary text-primary-fg border-primary" : "border-border bg-bg"}`}
                    onClick={() => {
                      setTab(kind);
                      const next = analysis.choices.find((item) => item.kind === kind && item.is_default) || analysis.choices.find((item) => item.kind === kind);
                      setChoiceId(next?.choice_id || null);
                      setConsent(false);
                    }}
                  >
                    {kind === "mp4" ? t.tabMp4 : kind === "mp3" ? t.tabMp3 : t.tabOriginal}
                  </button>
                ))}
              </div>
              {choices.length === 0 ? <p className="text-muted text-sm">{t.noChoice}</p> : null}
              <div className="grid gap-2" role="radiogroup" aria-label={t.confirmLabel}>
                {choices.map((choice) => (
                  <label key={choice.choice_id} className="border-border bg-bg grid gap-1 rounded-md border px-3 py-3 text-sm">
                    <span className="flex items-center gap-2 font-medium">
                      <input
                        type="radio"
                        name="choice"
                        checked={choiceId === choice.choice_id}
                        onChange={() => {
                          setChoiceId(choice.choice_id);
                          setConsent(false);
                        }}
                      />
                      {choice.label}
                      {choice.portrait ? <span className="text-muted font-normal">{t.portrait}</span> : null}
                    </span>
                    <span className="text-muted">
                      {[choice.resolution_label, choice.width && choice.height ? `${choice.width}×${choice.height}` : null, choice.vcodec, choice.acodec, choice.fps ? `${choice.fps} fps` : null]
                        .filter(Boolean)
                        .join(" · ")}
                      {choice.audio_language ? ` · ${choice.audio_language}` : ""}
                      {choice.audio_role ? ` · ${t.role[choice.audio_role as "original"] || choice.audio_role}` : ""}
                      {choice.estimated_bytes != null ? ` · ${choice.size_is_estimate ? t.estimate + " " : ""}${formatBytes(choice.estimated_bytes)}` : ""}
                    </span>
                  </label>
                ))}
              </div>
              <details className="text-sm">
                <summary className="cursor-pointer">{t.details}</summary>
                <p className="text-muted mt-2 leading-relaxed">{tab === "mp3" ? t.bitrateNote : tab === "original_audio" ? t.originalNote : t.conversionNote}</p>
              </details>
              {selected ? (
                <p className="text-sm">
                  <span className="font-medium">{t.confirmLabel}: </span>
                  {selected.label}. {selected.conversion_required || selected.kind === "mp3" ? t.convert : t.copy}
                </p>
              ) : null}
              {selected?.requires_consent ? (
                <label className="flex items-start gap-2 text-sm">
                  <input type="checkbox" className="mt-1" checked={consent} onChange={(event) => setConsent(event.target.checked)} />
                  {t.consent}
                </label>
              ) : null}
              <label className="flex items-start gap-2 text-sm">
                <input type="checkbox" className="mt-1" checked={keep} onChange={(event) => setKeep(event.target.checked)} />
                <span>
                  {t.keep}
                  <span className="text-muted block">{t.keepHint}</span>
                  {settings ? (
                    <span className="text-muted block">
                      {t.quota}: {formatBytes(settings.capabilities.storage_used_bytes)} / {formatBytes(settings.capabilities.storage_limit_bytes)}
                    </span>
                  ) : null}
                </span>
              </label>
              <button className="bg-primary text-primary-fg h-11 rounded-md font-medium" type="button" disabled={!selected || busy || (selected.requires_consent && !consent)} onClick={() => void onCreate()}>
                {t.create}
              </button>
            </section>
          ) : null}

          <section className="grid gap-3" aria-live="polite">
            <div className="flex items-center justify-between">
              <h2 className="text-lg font-semibold">{t.jobs}</h2>
              <span className="text-muted text-xs">{live === "live" ? t.live : t.polling}</span>
            </div>
            {active.length === 0 ? <p className="text-muted text-sm">{t.emptyJobs}</p> : active.map((job) => <JobCard key={job.id} job={job} locale={locale} onChange={() => void refreshJobs()} csrf={csrf} onRetry={beginRetry} />)}
          </section>
          <section className="grid gap-3">
            <h2 className="text-lg font-semibold">{t.history}</h2>
            {history.length === 0 ? <p className="text-muted text-sm">{t.emptyHistory}</p> : history.map((job) => <JobCard key={job.id} job={job} locale={locale} onChange={() => void refreshJobs()} csrf={csrf} onRetry={beginRetry} />)}
          </section>
          {settings?.capabilities.playlists_enabled ? (
            <section className="border-border bg-surface grid gap-3 rounded-md border p-4">
              <h2 className="text-lg font-semibold">{t.playlistTitle}</h2>
              <p className="text-muted text-sm leading-relaxed">{t.playlistHint}</p>
              <form
                className="flex gap-2"
                onSubmit={(event) => {
                  event.preventDefault();
                  setPlaylistError(null);
                  setBusy(true);
                  api
                    .playlist(csrf, locale, playlistUrl.trim())
                    .then(setPlaylist)
                    .catch((error) => setPlaylistError(messageOf(error)))
                    .finally(() => setBusy(false));
                }}
              >
                <input
                  className="border-border bg-bg h-11 flex-1 rounded-md border px-3"
                  value={playlistUrl}
                  onChange={(event) => setPlaylistUrl(event.target.value)}
                  placeholder="https://www.youtube.com/playlist?list="
                  aria-label={t.playlistTitle}
                />
                <button className="bg-primary text-primary-fg h-11 rounded-md px-3 text-sm" type="submit" disabled={busy}>
                  {t.analyze}
                </button>
              </form>
              {playlistError ? <p className="text-danger text-sm" role="alert">{playlistError}</p> : null}
              {playlist?.limited ? <p className="text-muted text-sm">{t.playlistLimited}</p> : null}
              <ul className="grid gap-2">
                {playlist?.entries.map((entry) => (
                  <li key={entry.position} className="border-border bg-bg flex items-center justify-between gap-3 rounded-md border px-3 py-2 text-sm">
                    <span className="min-w-0">
                      <span className="text-muted mr-2">{entry.position}</span>
                      {entry.title || t.unknown}
                      {!entry.available ? <span className="text-danger ml-2">{entry.reason || t.playlistUnavailable}</span> : null}
                    </span>
                    {entry.available && entry.canonical_url ? (
                      <button
                        type="button"
                        className="shrink-0 underline"
                        onClick={() => {
                          setUrl(entry.canonical_url || "");
                          setParentId(null);
                          setAnalysis(null);
                        }}
                      >
                        {t.playlistUse}
                      </button>
                    ) : null}
                  </li>
                ))}
              </ul>
            </section>
          ) : null}
          <button type="button" className="text-muted text-left text-sm underline" onClick={() => void showDiag()}>
            {t.diagnostics}
          </button>
          {diag ? (
            <pre className="border-border bg-surface overflow-auto rounded-md border p-3 text-xs">{diag}</pre>
          ) : null}
        </>
      ) : null}
    </main>
  );

  function switchLocale(next: Locale) {
    setLocale(next);
    if (csrf) api.patchSettings(csrf, { language: next }).then(setSettings).catch(() => undefined);
  }

  function cycleTheme() {
    const order = ["system", "light", "dark"] as const;
    const next = order[(order.indexOf(theme) + 1) % order.length];
    setTheme(next);
    applyTheme(next);
    if (csrf) api.patchSettings(csrf, { theme: next }).catch(() => undefined);
  }

  function beginRetry(job: Job) {
    setParentId(job.id);
    setUrl(job.source.canonical_url || "");
    setAnalysis(null);
    setUrlError(null);
  }

  async function logout() {
    if (!csrf) return;
    await api.logout(csrf);
    setSession({ authenticated: false, bootstrapped: true });
    setGate("login");
  }

  async function showDiag() {
    if (!csrf) return;
    const value = await api.diagnostics(csrf);
    setDiag(JSON.stringify(value, null, 2));
  }
}

function JobCard({ job, locale, csrf, onChange, onRetry }: { job: Job; locale: Locale; csrf: string; onChange: () => void; onRetry: (job: Job) => void }) {
  const t = translate(locale);
  const percent = job.progress?.percent;
  const known = typeof percent === "number" && job.progress?.total_bytes != null && !job.progress.total_is_estimate;
  return (
    <article className="border-border bg-surface grid gap-2 rounded-md border p-4">
      <div className="flex items-start justify-between gap-3">
        <div>
          <h3 className="font-medium">{job.source.title || job.output.label}</h3>
          <p className="text-muted text-sm">
            {t.status[job.status]}
            {job.phase ? ` · ${t.phase[job.phase as "downloading"] || job.phase}` : ""}
            {job.queue_position ? ` · ${t.queue} ${job.queue_position}` : ""}
          </p>
        </div>
        <p className="text-muted text-xs">{new Date(job.updated_at).toLocaleString(locale === "ko" ? "ko-KR" : "en")}</p>
      </div>
      {job.status === "running" || job.status === "queued" ? (
        <div className="bg-bg h-2 overflow-hidden rounded-full" role="progressbar" aria-valuemin={0} aria-valuemax={100} aria-valuenow={known ? Math.round(percent || 0) : undefined} aria-label={job.phase || job.status}>
          <div className={known ? "bg-primary h-full" : "indeterminate h-full"} style={known ? { width: `${percent}%` } : undefined} />
        </div>
      ) : null}
      {job.progress && (job.status === "running" || job.status === "queued") ? (
        <p className="text-muted text-xs">
          {job.progress.total_bytes == null ? t.unknownProgress : null}
          {job.progress.speed_bps != null ? ` ${t.speed} ${formatBytes(job.progress.speed_bps)}/s` : ""}
          {job.progress.eta_seconds != null ? ` · ${t.eta} ${formatDuration(job.progress.eta_seconds)}` : ""}
        </p>
      ) : null}
      {job.cancel_requested && job.status === "running" ? <p className="text-sm">{t.cancelling}</p> : null}
      {job.error ? (
        <p className="text-danger text-sm" role="alert">
          {job.error.message} {job.error.action}
        </p>
      ) : null}
      <p className="text-muted text-xs">
        {t.fileState[job.file_state]}
        {job.artifact ? ` · ${formatBytes(job.artifact.bytes)} · ${job.keep_on_server ? t.stored : job.artifact.expires_at ? new Date(job.artifact.expires_at).toLocaleString(locale === "ko" ? "ko-KR" : "en") : ""}` : ""}
        {job.file_state === "available" ? ` · ${t.folder}: ${t.logicalFolder}` : ""}
      </p>
      <div className="flex flex-wrap gap-2">
        {job.file_state === "available" ? (
          <a className="bg-primary text-primary-fg inline-flex h-11 items-center gap-2 rounded-md px-3 text-sm" href={`/api/v1/jobs/${job.id}/file`}>
            <Download className="size-4" /> {t.download}
          </a>
        ) : null}
        {job.status === "queued" || job.status === "running" ? (
          <button type="button" className="border-border h-11 rounded-md border px-3 text-sm" onClick={() => void api.cancel(csrf, job.id).then(onChange)}>
            {t.cancel}
          </button>
        ) : null}
        {job.file_state === "available" ? (
          <button type="button" className="border-border h-11 rounded-md border px-3 text-sm" onClick={() => void api.retention(csrf, job.id, !job.keep_on_server).then(onChange)}>
            {job.keep_on_server ? t.expire : t.keep}
          </button>
        ) : null}
        {job.file_state === "available" ? (
          <button type="button" className="border-border h-11 rounded-md border px-3 text-sm" onClick={() => void api.deleteFile(csrf, job.id).then(onChange)}>
            {t.deleteFile}
          </button>
        ) : null}
        {job.status !== "queued" && job.status !== "running" ? (
          <button type="button" className="border-border h-11 rounded-md border px-3 text-sm" onClick={() => onRetry(job)}>
            {t.retry}
          </button>
        ) : null}
        {job.file_state !== "available" && job.status !== "queued" && job.status !== "running" ? (
          <button type="button" className="border-border h-11 rounded-md border px-3 text-sm" onClick={() => void api.deleteHistory(csrf, job.id).then(onChange)}>
            {t.deleteHistory}
          </button>
        ) : null}
      </div>
      {job.status === "running" ? <LoaderCircle className="text-muted size-4 animate-spin" aria-hidden="true" /> : null}
    </article>
  );
}

function messageOf(error: unknown): string {
  if (error && typeof error === "object" && "body" in error) {
    const body = (error as { body?: { error?: { message?: string; action?: string } } }).body;
    if (body?.error?.message) return `${body.error.message} ${body.error.action || ""}`.trim();
  }
  if (error instanceof Error) return error.message;
  return "Error";
}
