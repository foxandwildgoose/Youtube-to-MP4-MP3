import { useEffect, useMemo, useRef, useState, type FormEvent } from "react";
import * as Tabs from "@radix-ui/react-tabs";
import {
  Archive,
  ArrowRight,
  ClipboardPaste,
  Film,
  Headphones,
  Link,
  LogOut,
  Search,
  ShieldCheck,
  X,
} from "lucide-react";
import type { Choice, Job } from "./api";
import { translate } from "./i18n";
import { useDownloaderController } from "./use-downloader-controller";
import { JobCard } from "./components/job-card";
import { SettingsDialog } from "./components/settings-dialog";
import { BusyLabel, ErrorNotice } from "./components/presentation";
import {
  choiceLabel,
  formatBytes,
  formatDate,
  formatDuration,
  outputSummary,
} from "./components/formatters";

type Mode = "mp4" | "mp3";
type Kind = Choice["kind"];
function semanticChoice(choice: Choice): string {
  return [
    choice.kind,
    choice.width,
    choice.height,
    choice.fps,
    choice.bitrate_kbps,
    choice.audio_language,
    choice.audio_role,
    choice.track_key,
    choice.container,
    choice.conversion_required,
  ].join("|");
}
function preferredChoice(choices: Choice[], kind: Kind, bitrate: number): Choice | undefined {
  const items = choices.filter((choice) => choice.kind === kind);
  return (
    (kind === "mp3"
      ? items.find((choice) => choice.bitrate_kbps === bitrate && choice.is_default) ||
        items.find((choice) => choice.bitrate_kbps === bitrate)
      : undefined) ||
    items.find((choice) => choice.is_default) ||
    items.find((choice) => !choice.requires_consent) ||
    items[0]
  );
}

export function DownloaderApp() {
  const c = useDownloaderController(),
    { locale, theme, analysis, settings } = c;
  const t = translate(locale);
  const [mode, setMode] = useState<Mode>("mp4");
  const [useOriginal, setUseOriginal] = useState(false);
  const [showConversion, setShowConversion] = useState(false);
  const [selectedIds, setSelectedIds] = useState<Partial<Record<Kind, string>>>({});
  const selectedSemantics = useRef<Partial<Record<Kind, string>>>({});
  const previousSource = useRef<string | null>(null);
  const [consentFor, setConsentFor] = useState<string | null>(null);
  const [keep, setKeep] = useState(false);
  const [password, setPassword] = useState("");
  const [confirmPassword, setConfirmPassword] = useState("");
  const [passwordError, setPasswordError] = useState<string | null>(null);
  const [clipboardNotice, setClipboardNotice] = useState<string | null>(null);
  const [playlistUrl, setPlaylistUrl] = useState("");
  const [historySearch, setHistorySearch] = useState("");
  const [thumbnailFailed, setThumbnailFailed] = useState(false);
  const [discardWarning, setDiscardWarning] = useState(false);
  const urlInput = useRef<HTMLInputElement>(null);
  const passwordInput = useRef<HTMLInputElement>(null);
  const analysisHeading = useRef<HTMLHeadingElement>(null);
  const activeHeading = useRef<HTMLHeadingElement>(null);
  const kind: Kind = mode === "mp3" && useOriginal ? "original_audio" : mode;
  const allModeChoices = useMemo(
    () => analysis?.choices.filter((choice) => choice.kind === kind) || [],
    [analysis, kind],
  );
  const choices = useMemo(
    () => allModeChoices.filter((choice) => showConversion || !choice.requires_consent),
    [allModeChoices, showConversion],
  );
  const selected = choices.find((choice) => choice.choice_id === selectedIds[kind]) || null;
  const consentKey = analysis && selected ? `${analysis.analysis_id}:${selected.choice_id}` : null;
  const consent = consentKey != null && consentFor === consentKey;
  const ready = c.gate === "ready";
  const setupAllowed =
    c.session && "bootstrap_allowed" in c.session ? Boolean(c.session.bootstrap_allowed) : false;
  const historyLimit = c.historyLimit;
  const historyFiltered = Boolean(
    c.historyQuery || c.historyFormat || c.historyStatus || c.historyFileState,
  );

  useEffect(() => {
    delete selectedSemantics.current.mp3;
  }, [c.mp3Bitrate]);

  useEffect(() => {
    if (!analysis) {
      setConsentFor(null);
      return;
    }
    const sameSource = previousSource.current === analysis.source.video_id;
    const next: Partial<Record<Kind, string>> = {};
    for (const outputKind of ["mp4", "mp3", "original_audio"] as const) {
      const previous = selectedSemantics.current[outputKind];
      const matching = previous
        ? analysis.choices.find(
            (choice) => choice.kind === outputKind && semanticChoice(choice) === previous,
          )
        : undefined;
      const fallback =
        sameSource && previous && !matching
          ? undefined
          : preferredChoice(analysis.choices, outputKind, analysis.effective_mp3_bitrate || 192);
      const choice = matching || fallback;
      if (choice) {
        next[outputKind] = choice.choice_id;
        selectedSemantics.current[outputKind] = semanticChoice(choice);
      }
    }
    previousSource.current = analysis.source.video_id;
    setSelectedIds(next);
    setConsentFor(null);
    setShowConversion(false);
    setThumbnailFailed(false);
  }, [analysis]);

  useEffect(() => {
    setPassword("");
    setConfirmPassword("");
    setPasswordError(null);
  }, [c.gate]);

  function selectChoice(id: string) {
    const choice = analysis?.choices.find((item) => item.choice_id === id);
    setSelectedIds((current) => ({ ...current, [kind]: id }));
    if (choice) selectedSemantics.current[kind] = semanticChoice(choice);
    setConsentFor(null);
    c.clearError("create");
  }
  function focusUrl() {
    urlInput.current?.focus();
    urlInput.current?.scrollIntoView({ block: "center", behavior: "auto" });
  }
  async function pasteUrl() {
    focusUrl();
    if (!navigator.clipboard?.readText) {
      setClipboardNotice(t.clipboardManual);
      return;
    }
    try {
      const text = await navigator.clipboard.readText();
      if (!text.trim()) {
        setClipboardNotice(t.clipboardEmpty);
        return;
      }
      c.setUrl(text.trim());
      setConsentFor(null);
      setClipboardNotice(t.pasted);
    } catch {
      setClipboardNotice(t.clipboardManual);
    }
  }
  async function analyzeUrl(event?: FormEvent) {
    event?.preventDefault();
    setClipboardNotice(null);
    setConsentFor(null);
    const value = c.url.trim();
    const result = await c.analyze(value);
    if (result) window.setTimeout(() => analysisHeading.current?.focus(), 0);
    else focusUrl();
  }
  async function submitAuth(event: FormEvent) {
    event.preventDefault();
    setPasswordError(null);
    if (c.gate === "setup" && password !== confirmPassword) {
      setPasswordError(t.mismatch);
      passwordInput.current?.focus();
      return;
    }
    if (c.gate === "setup") await c.bootstrap(password);
    else await c.login(password);
  }
  async function createFile() {
    if (!selected) return;
    const job = await c.create(selected.choice_id, keep, consent);
    if (job) window.setTimeout(() => activeHeading.current?.focus(), 0);
  }
  function prepareRetry(job: Job) {
    c.prepareRetry(job);
    setMode(job.output.kind === "mp4" ? "mp4" : "mp3");
    setUseOriginal(job.output.kind === "original_audio");
    setConsentFor(null);
    focusUrl();
  }
  function historyQuery(
    overrides: {
      search?: string;
      format?: "" | Kind;
      status?: string;
      file_state?: string;
      offset?: number;
    } = {},
  ) {
    void c.loadHistory({
      search: c.historyQuery,
      format: c.historyFormat,
      status: c.historyStatus,
      file_state: c.historyFileState,
      offset: 0,
      ...overrides,
    });
  }
  const renderJob = (job: Job) => (
    <JobCard
      key={job.id}
      job={job}
      locale={locale}
      error={c.errors.jobs[job.id]}
      pending={c.pendingJobs}
      onAction={(action, id, retain) => void c.mutateJob(action, id, retain)}
      onRetry={prepareRetry}
      onDownload={(value) => void c.download(value)}
    />
  );

  return (
    <main className="seorap-shell">
      <a className="skip-link" href="#main-task">
        {t.urlLabel}
      </a>
      <header className="app-header">
        <div className="brand">
          <span className="brand-mark" aria-hidden="true">
            <Archive />
          </span>
          <div>
            <h1>{t.name}</h1>
            <p>{t.tagline}</p>
          </div>
        </div>
        <div className="header-actions">
          <SettingsDialog
            locale={locale}
            theme={theme}
            settings={settings}
            ready={ready}
            busy={c.preferencesBusy}
            error={c.errors.preferences}
            diagnosticsError={c.errors.diagnostics}
            diagnosticsValue={c.diagnosticsValue}
            onSave={(values) => void c.savePreferences(values)}
            onDiagnostics={() => void c.diagnostics()}
            diagnosticsBusy={c.diagnosticsBusy}
            processingReady={c.processingReady}
          />
          {ready && c.session?.password_required !== false ? (
            <button
              className="button secondary compact"
              type="button"
              disabled={c.authBusy}
              onClick={() => void c.logout()}
            >
              <LogOut className="icon" aria-hidden="true" />
              <span>{c.authBusy ? t.signingOut : t.logout}</span>
            </button>
          ) : null}
        </div>
      </header>
      {ready ? <ErrorNotice error={c.errors.auth} locale={locale} /> : null}
      {c.gate === "boot" ? (
        <section className="gate-card" id="main-task" aria-busy="true">
          <BusyLabel busy>{t.checking}</BusyLabel>
        </section>
      ) : null}
      {c.gate === "offline" ? (
        <section className="gate-card" id="main-task">
          <h2>{t.offlineTitle}</h2>
          <p className="muted">{t.offlineBody}</p>
          <ErrorNotice error={c.errors.connection} locale={locale} />
          <button
            className="button primary"
            type="button"
            disabled={c.authBusy}
            onClick={() => void c.retryConnection()}
          >
            <BusyLabel busy={c.authBusy}>{t.checkAgain}</BusyLabel>
          </button>
        </section>
      ) : null}
      {c.gate === "login" || c.gate === "setup" ? (
        <section className="gate-card" id="main-task">
          <span className="section-eyebrow">
            <ShieldCheck className="icon" aria-hidden="true" />
            {t.name}
          </span>
          <h2>{c.gate === "login" ? t.loginTitle : t.setupTitle}</h2>
          <p className="muted">{c.gate === "login" ? t.loginBody : t.setupBody}</p>
          {c.gate === "setup" && !setupAllowed ? (
            <div className="cli-setup">
              <p>{t.cliSetup}</p>
              <code>docker compose exec app python -m app.cli bootstrap</code>
              <p className="small muted">{t.cliNext}</p>
              <button
                className="button primary"
                type="button"
                disabled={c.authBusy}
                onClick={() => void c.retryConnection()}
              >
                <BusyLabel busy={c.authBusy}>{t.checkAgain}</BusyLabel>
              </button>
            </div>
          ) : (
            <form
              className="auth-form"
              onSubmit={(event) => void submitAuth(event)}
              aria-busy={c.authBusy}
            >
              <label className="field" htmlFor="local-password">
                <span>{t.password}</span>
                <input
                  id="local-password"
                  name="password"
                  ref={passwordInput}
                  type="password"
                  autoComplete={c.gate === "setup" ? "new-password" : "current-password"}
                  minLength={c.gate === "setup" ? 10 : undefined}
                  required
                  value={password}
                  onChange={(event) => {
                    setPassword(event.target.value);
                    setPasswordError(null);
                    c.clearError("auth");
                  }}
                  aria-invalid={Boolean(passwordError || c.errors.auth)}
                  aria-describedby={`${c.gate === "setup" ? "password-hint " : ""}auth-error`}
                />
              </label>
              {c.gate === "setup" ? (
                <>
                  <p className="small muted" id="password-hint">
                    {t.passwordHint}
                  </p>
                  <label className="field" htmlFor="confirm-password">
                    <span>{t.confirm}</span>
                    <input
                      id="confirm-password"
                      name="confirm-password"
                      type="password"
                      autoComplete="new-password"
                      minLength={10}
                      required
                      value={confirmPassword}
                      onChange={(event) => setConfirmPassword(event.target.value)}
                    />
                  </label>
                </>
              ) : null}
              <div id="auth-error">
                {passwordError ? (
                  <p className="error-note" role="alert">
                    {passwordError}
                  </p>
                ) : null}
                <ErrorNotice error={c.errors.auth} locale={locale} />
              </div>
              <button className="button primary" type="submit" disabled={c.authBusy}>
                <BusyLabel busy={c.authBusy}>
                  {c.authBusy
                    ? c.gate === "login"
                      ? t.signingIn
                      : t.saving
                    : c.gate === "login"
                      ? t.login
                      : t.savePassword}
                </BusyLabel>
              </button>
            </form>
          )}
        </section>
      ) : null}
      {ready ? (
        <>
          <section className="download-workspace" id="main-task" aria-labelledby="task-title">
            <div className="workspace-intro">
              <p className="section-eyebrow">YouTube → MP4 / MP3</p>
              <h2 id="task-title">{t.headline}</h2>
              <p className="muted">{t.intro}</p>
            </div>
            {settings?.capabilities.demo_data ? (
              <p className="info-note test-note">{t.demo}</p>
            ) : null}
            {c.processingReady === false ? (
              <div className="info-note">
                <p>{t.processorUnavailable}</p>
                <button
                  type="button"
                  className="text-button"
                  onClick={() => void c.refreshStorage()}
                >
                  {t.checkAgain}
                </button>
              </div>
            ) : null}
            {c.cooldownSeconds > 0 ? (
              <p className="info-note numeric" role="status">
                {t.retryAfter} {c.cooldownSeconds} {t.seconds}
              </p>
            ) : null}
            <Tabs.Root
              value={mode}
              onValueChange={(value) => {
                setMode(value as Mode);
                setConsentFor(null);
              }}
              className="mode-tabs"
            >
              <Tabs.List className="mode-list" aria-label={t.selection}>
                <Tabs.Trigger className="mode-tab" value="mp4">
                  <Film className="icon" aria-hidden="true" />
                  {t.tabMp4}
                </Tabs.Trigger>
                <Tabs.Trigger className="mode-tab" value="mp3">
                  <Headphones className="icon" aria-hidden="true" />
                  {t.tabMp3}
                </Tabs.Trigger>
              </Tabs.List>
              <form
                className="url-form"
                onSubmit={(event) => void analyzeUrl(event)}
                aria-busy={c.analysisBusy}
              >
                <label className="field" htmlFor="video-url">
                  <span>{t.urlLabel}</span>
                  <div className="url-input-wrap">
                    <Link className="icon" aria-hidden="true" />
                    <input
                      ref={urlInput}
                      id="video-url"
                      name="video-url"
                      type="url"
                      inputMode="url"
                      autoComplete="off"
                      spellCheck={false}
                      placeholder="https://www.youtube.com/watch?v=…"
                      value={c.url}
                      required
                      aria-describedby="url-hint url-feedback"
                      aria-invalid={Boolean(c.errors.analyze)}
                      onChange={(event) => {
                        c.setUrl(event.target.value);
                        setConsentFor(null);
                        setClipboardNotice(null);
                      }}
                    />
                    <button
                      type="button"
                      className="icon-button"
                      disabled={!c.url}
                      onClick={() => {
                        c.setUrl("");
                        setConsentFor(null);
                        setClipboardNotice(null);
                        focusUrl();
                      }}
                      aria-label={t.clear}
                    >
                      <X className="icon" aria-hidden="true" />
                    </button>
                  </div>
                </label>
                <div className="url-actions">
                  <button
                    type="button"
                    className="button secondary"
                    onClick={() => void pasteUrl()}
                  >
                    <ClipboardPaste className="icon" aria-hidden="true" />
                    {t.paste}
                  </button>
                  <button
                    type="submit"
                    className="button primary"
                    disabled={c.analysisBusy || c.submitting || c.cooldownSeconds > 0}
                  >
                    <BusyLabel busy={c.analysisBusy}>
                      {c.analysisBusy ? t.analyzing : t.analyze}
                    </BusyLabel>
                    {!c.analysisBusy ? <ArrowRight className="icon" aria-hidden="true" /> : null}
                  </button>
                </div>
                <p id="url-hint" className="small muted">
                  {t.urlHint}
                </p>
                <div id="url-feedback">
                  {clipboardNotice ? (
                    <p className="small muted" role="status">
                      {clipboardNotice}
                    </p>
                  ) : null}
                  <ErrorNotice
                    error={c.errors.analyze}
                    locale={locale}
                    onRetry={() => void analyzeUrl()}
                    retryLabel={t.reanalyze}
                  />
                </div>
                {c.analysisBusy ? (
                  <div className="small muted">
                    <button
                      type="button"
                      className="text-button"
                      onClick={() => c.cancelAnalysis()}
                    >
                      {t.cancelAnalysis}
                    </button>
                    <p>{t.cancelAnalysisHint}</p>
                  </div>
                ) : null}
              </form>
              {c.parentId ? (
                <div className="info-note">
                  <p>{t.retryHint}</p>
                  <button type="button" className="text-button" onClick={c.clearRetry}>
                    {t.clearRetry}
                  </button>
                </div>
              ) : null}
              {analysis ? (
                <div className="analysis-result" key={analysis.analysis_id}>
                  <div className="source-card">
                    <div className="source-thumbnail">
                      {analysis.source.thumbnail_url && !thumbnailFailed ? (
                        <img
                          src={analysis.source.thumbnail_url}
                          alt=""
                          loading="lazy"
                          onError={() => setThumbnailFailed(true)}
                        />
                      ) : (
                        <span>
                          <Film className="icon" aria-hidden="true" />
                          {t.noThumb}
                        </span>
                      )}
                      <span className="thumbnail-duration numeric">
                        {formatDuration(analysis.source.duration_seconds)}
                      </span>
                    </div>
                    <div className="source-copy">
                      <p className="section-eyebrow">{t.metadata}</p>
                      <h3 ref={analysisHeading} tabIndex={-1}>
                        {analysis.source.title}
                      </h3>
                      <p className="muted small">{analysis.source.channel || t.unknown}</p>
                      <a
                        className="text-link small"
                        href={analysis.source.canonical_url}
                        target="_blank"
                        rel="noreferrer"
                      >
                        {t.source} ↗
                      </a>
                      <p className="source-id small muted">
                        {t.sourceIdentity}: {analysis.source.video_id}
                      </p>
                    </div>
                  </div>
                  {analysis.source.ignored_timestamp ? (
                    <p className="small muted">{t.timestamp}</p>
                  ) : null}
                  {analysis.source.ignored_playlist ? (
                    <p className="small muted">{t.playlistIgnored}</p>
                  ) : null}
                  {(["mp4", "mp3"] as const).map((panelMode) => (
                    <Tabs.Content
                      key={panelMode}
                      value={panelMode}
                      className="choice-panel"
                      aria-label={panelMode === "mp4" ? t.tabMp4 : t.tabMp3}
                    >
                      <div className="choice-topline">
                        <h4>{t.confirmLabel}</h4>
                        <span className="small muted">
                          {kind === "mp3"
                            ? t.audioEncoding
                            : kind === "original_audio"
                              ? t.tabOriginal
                              : t.tabMp4}
                        </span>
                      </div>
                      {choices.length ? (
                        <label className="field" htmlFor={`quality-${panelMode}`}>
                          <span className="small muted">{t.quality}</span>
                          <select
                            id={`quality-${panelMode}`}
                            value={selected?.choice_id || ""}
                            onChange={(event) => selectChoice(event.target.value)}
                            aria-describedby={`choice-facts-${panelMode}`}
                          >
                            <option value="" disabled>
                              {t.selection}
                            </option>
                            {choices.map((choice) => (
                              <option key={choice.choice_id} value={choice.choice_id}>
                                {choiceLabel(choice, locale)}
                              </option>
                            ))}
                          </select>
                        </label>
                      ) : (
                        <p className="info-note">{t.noChoice}</p>
                      )}
                      {selected ? (
                        <div className="selected-output" id={`choice-facts-${panelMode}`}>
                          <strong>{outputSummary(selected, locale)}</strong>
                          <span className="small muted">
                            {selected.kind === "mp3"
                              ? t.audioEncoding
                              : selected.conversion_required
                                ? t.convert
                                : t.copy}
                          </span>
                          <span className="small numeric">
                            {t.outputSize}:{" "}
                            {(selected.estimated_output_bytes !== undefined
                              ? selected.estimated_output_bytes
                              : selected.estimated_bytes) == null
                              ? t.unknown
                              : `${selected.output_size_provenance === "exact" ? `${t.exact} ` : `${t.estimate} `}${formatBytes(selected.estimated_output_bytes !== undefined ? selected.estimated_output_bytes : selected.estimated_bytes)}`}
                          </span>
                          {selected.audio_language ? (
                            <span className="small muted">
                              {t.audioLanguage}: {selected.audio_language}
                              {selected.audio_role && selected.audio_role in t.role
                                ? ` · ${t.role[selected.audio_role as keyof typeof t.role]}`
                                : ""}
                            </span>
                          ) : null}
                        </div>
                      ) : null}
                      {panelMode === "mp3" ? (
                        <p className="small muted">
                          {kind === "original_audio" ? t.originalNote : t.bitrateNote}
                        </p>
                      ) : null}
                      <details className="advanced-options">
                        <summary>{t.advanced}</summary>
                        <div className="advanced-content">
                          {panelMode === "mp4" ? (
                            settings?.capabilities.transcoding_enabled ? (
                              <label className="check-label">
                                <input
                                  type="checkbox"
                                  checked={showConversion}
                                  onChange={(event) => {
                                    setShowConversion(event.target.checked);
                                    setConsentFor(null);
                                  }}
                                />
                                <span>
                                  {t.conversionOption}
                                  <span className="small muted">{t.conversionNote}</span>
                                </span>
                              </label>
                            ) : (
                              <p className="small muted">{t.conversionUnavailable}</p>
                            )
                          ) : (
                            <label className="check-label">
                              <input
                                type="checkbox"
                                checked={useOriginal}
                                disabled={
                                  !analysis.choices.some(
                                    (choice) => choice.kind === "original_audio",
                                  )
                                }
                                onChange={(event) => {
                                  setUseOriginal(event.target.checked);
                                  setConsentFor(null);
                                }}
                              />
                              <span>
                                {t.originalOption}
                                <span className="small muted">{t.originalNote}</span>
                              </span>
                            </label>
                          )}
                          {selected ? (
                            <dl className="fact-list small">
                              <div>
                                <dt>{t.details}</dt>
                                <dd>
                                  {[
                                    selected.container.toUpperCase(),
                                    selected.vcodec,
                                    selected.acodec,
                                    selected.width && selected.height
                                      ? `${selected.width}×${selected.height}`
                                      : null,
                                  ]
                                    .filter(Boolean)
                                    .join(" · ")}
                                </dd>
                              </div>
                              <div>
                                <dt>{t.inputSize}</dt>
                                <dd>
                                  {selected.input_bytes == null
                                    ? t.unknown
                                    : `${selected.input_size_provenance === "exact" ? t.exact : t.estimate} ${formatBytes(selected.input_bytes)}`}
                                </dd>
                              </div>
                              <div>
                                <dt>{t.workspaceBudget}</dt>
                                <dd>
                                  {selected.expected_workspace_bytes == null
                                    ? t.unknown
                                    : `${t.estimate} ${formatBytes(selected.expected_workspace_bytes)}`}
                                </dd>
                              </div>
                              <div>
                                <dt>{t.analysisExpires}</dt>
                                <dd>{formatDate(analysis.expires_at, locale)}</dd>
                              </div>
                            </dl>
                          ) : null}
                          <details className="technical-details">
                            <summary>
                              {t.allFormats} ({allModeChoices.length})
                            </summary>
                            <ul className="format-list">
                              {allModeChoices.map((choice) => (
                                <li key={choice.choice_id}>
                                  <span>{choiceLabel(choice, locale)}</span>
                                  <span className="small muted">
                                    {[
                                      choice.vcodec,
                                      choice.acodec,
                                      choice.estimated_bytes == null
                                        ? t.unknown
                                        : `${choice.size_is_estimate ? `${t.estimate} ` : ""}${formatBytes(choice.estimated_bytes)}`,
                                    ]
                                      .filter(Boolean)
                                      .join(" · ")}
                                  </span>
                                </li>
                              ))}
                            </ul>
                          </details>
                        </div>
                      </details>
                      {selected?.requires_consent ? (
                        <label className="check-label consent-label">
                          <input
                            type="checkbox"
                            checked={consent}
                            onChange={(event) =>
                              setConsentFor(event.target.checked ? consentKey : null)
                            }
                          />
                          <span>
                            {t.consent}
                            <span className="small muted">{t.conversionNote}</span>
                          </span>
                        </label>
                      ) : null}
                      <label className="check-label">
                        <input
                          type="checkbox"
                          checked={keep}
                          onChange={(event) => setKeep(event.target.checked)}
                        />
                        <span>
                          {t.keep}
                          <span className="small muted">{t.keepHint}</span>
                        </span>
                      </label>
                      {c.analysisExpired ? (
                        <div className="info-note">
                          <p>{t.expiredAnalysis}</p>
                          <button
                            className="text-button"
                            type="button"
                            onClick={() => void analyzeUrl()}
                          >
                            {t.reanalyze}
                          </button>
                        </div>
                      ) : null}
                      <ErrorNotice
                        error={c.errors.create}
                        locale={locale}
                        onRetry={
                          c.errors.create?.code === "ANALYSIS_EXPIRED" ||
                          c.errors.create?.code === "FORMAT_CHANGED"
                            ? () => void analyzeUrl()
                            : undefined
                        }
                        retryLabel={t.reanalyze}
                      />
                      <button
                        className="button primary create-button"
                        type="button"
                        disabled={
                          !selected ||
                          c.submitting ||
                          c.analysisBusy ||
                          c.cooldownSeconds > 0 ||
                          c.analysisExpired ||
                          Boolean(c.pendingIntent) ||
                          Boolean(selected?.requires_consent && !consent)
                        }
                        onClick={() => void createFile()}
                      >
                        <BusyLabel busy={c.submitting}>
                          {c.submitting
                            ? t.creating
                            : kind === "mp4"
                              ? t.createMp4
                              : kind === "mp3"
                                ? t.createMp3
                                : t.createOriginal}
                        </BusyLabel>
                      </button>
                    </Tabs.Content>
                  ))}
                </div>
              ) : (
                <>
                  {(["mp4", "mp3"] as const).map((panelMode) => (
                    <Tabs.Content
                      key={panelMode}
                      value={panelMode}
                      className="mode-description small muted"
                    >
                      {panelMode === "mp4"
                        ? `${t.tabMp4} · H.264 / AAC`
                        : `${t.tabMp3} · ${settings?.mp3_bitrate || 192} kbps`}
                    </Tabs.Content>
                  ))}
                </>
              )}
            </Tabs.Root>
            {c.pendingIntent ? (
              <div className="info-note uncertain-note">
                <p>{t.uncertain}</p>
                {!analysis ? <ErrorNotice error={c.errors.create} locale={locale} /> : null}
                <div className="job-actions">
                  <button
                    type="button"
                    className="button primary"
                    disabled={c.submitting || c.cooldownSeconds > 0}
                    onClick={() => void c.replaySubmission()}
                  >
                    <BusyLabel busy={c.submitting}>{t.replay}</BusyLabel>
                  </button>
                  <button
                    type="button"
                    className="text-button"
                    onClick={() => setDiscardWarning(true)}
                  >
                    {t.discard}
                  </button>
                </div>
                {discardWarning ? (
                  <div>
                    <p className="small">{t.discardWarning}</p>
                    <div className="job-actions">
                      <button
                        type="button"
                        className="button secondary"
                        onClick={() => {
                          c.discardSubmission();
                          setDiscardWarning(false);
                        }}
                      >
                        {t.discard}
                      </button>
                      <button
                        type="button"
                        className="text-button"
                        onClick={() => setDiscardWarning(false)}
                      >
                        {t.back}
                      </button>
                    </div>
                  </div>
                ) : null}
              </div>
            ) : null}
          </section>
          <section className="jobs-section" aria-labelledby="active-title">
            <div className="section-heading">
              <h2 id="active-title" ref={activeHeading} tabIndex={-1}>
                {t.jobs} <span className="count">{c.active.length}</span>
              </h2>
              <span className="connection-state small" role="status">
                <span className={`connection-dot ${c.live === "live" ? "is-live" : ""}`} />
                {t[c.live]}
              </span>
            </div>
            <ErrorNotice
              error={c.errors.connection}
              locale={locale}
              onRetry={() => void c.retryConnection()}
            />
            {c.active.length ? (
              <div className="job-list">{c.active.map(renderJob)}</div>
            ) : (
              <p className="empty-state">{t.emptyJobs}</p>
            )}
          </section>
          <section className="history-section" aria-labelledby="history-title">
            <div className="section-heading">
              <h2 id="history-title">
                {t.history} <span className="count">{c.historyTotal}</span>
              </h2>
              <button
                className="text-button small"
                type="button"
                disabled={c.historyLoading}
                onClick={() => historyQuery({ offset: c.historyOffset })}
              >
                {t.refresh}
              </button>
            </div>
            <form
              className="history-search"
              onSubmit={(event) => {
                event.preventDefault();
                historyQuery({ search: historySearch });
              }}
            >
              <label className="field" htmlFor="history-search">
                <span className="sr-only">{t.search}</span>
                <div className="url-input-wrap">
                  <Search className="icon" aria-hidden="true" />
                  <input
                    id="history-search"
                    type="search"
                    value={historySearch}
                    onChange={(event) => setHistorySearch(event.target.value)}
                    placeholder={t.search}
                  />
                </div>
              </label>
              <button type="submit" className="button secondary" disabled={c.historyLoading}>
                {t.searchAction}
              </button>
            </form>
            <div className="history-filters">
              <label className="field">
                <span className="small muted">{t.formatFilter}</span>
                <select
                  value={c.historyFormat}
                  onChange={(event) => historyQuery({ format: event.target.value as "" | Kind })}
                >
                  <option value="">{t.all}</option>
                  <option value="mp4">MP4</option>
                  <option value="mp3">MP3</option>
                  <option value="original_audio">{t.tabOriginal}</option>
                </select>
              </label>
              <label className="field">
                <span className="small muted">{t.statusFilter}</span>
                <select
                  value={c.historyStatus}
                  onChange={(event) => historyQuery({ status: event.target.value })}
                >
                  <option value="">{t.all}</option>
                  {(["succeeded", "failed", "cancelled", "interrupted"] as const).map((status) => (
                    <option value={status} key={status}>
                      {t.status[status]}
                    </option>
                  ))}
                </select>
              </label>
              <label className="field">
                <span className="small muted">{t.fileFilter}</span>
                <select
                  value={c.historyFileState}
                  onChange={(event) => historyQuery({ file_state: event.target.value })}
                >
                  <option value="">{t.all}</option>
                  {(["available", "expired", "deleted", "missing", "none"] as const).map(
                    (state) => (
                      <option value={state} key={state}>
                        {t.fileState[state]}
                      </option>
                    ),
                  )}
                </select>
              </label>
            </div>
            <ErrorNotice
              error={c.errors.history}
              locale={locale}
              onRetry={() => historyQuery({ offset: c.historyOffset })}
            />
            <div aria-busy={c.historyLoading} className="job-list">
              {c.history.length ? (
                c.history.map(renderJob)
              ) : (
                <p className="empty-state">
                  {c.historyLoading
                    ? t.loadingHistory
                    : historyFiltered
                      ? t.emptySearch
                      : t.emptyHistory}
                </p>
              )}
            </div>
            <nav className="pagination" aria-label={t.history}>
              <button
                type="button"
                className="button secondary"
                disabled={c.historyLoading || c.historyOffset === 0}
                onClick={() =>
                  historyQuery({ offset: Math.max(0, c.historyOffset - historyLimit) })
                }
              >
                {t.previous}
              </button>
              <p className="small muted numeric" role="status">
                {c.historyTotal
                  ? `${c.historyOffset + 1}–${Math.min(c.historyOffset + c.history.length, c.historyTotal)} / ${c.historyTotal}`
                  : `0 ${t.records}`}
              </p>
              <button
                type="button"
                className="button secondary"
                disabled={c.historyLoading || c.historyOffset + c.history.length >= c.historyTotal}
                onClick={() => historyQuery({ offset: c.historyOffset + historyLimit })}
              >
                {t.next}
              </button>
            </nav>
            <p className="small muted device-note">{t.deviceNote}</p>
          </section>
          {settings?.capabilities.playlists_enabled ? (
            <details className="playlist-section">
              <summary>{t.playlistTitle}</summary>
              <p className="small muted">{t.playlistHint}</p>
              <form
                onSubmit={(event) => {
                  event.preventDefault();
                  void c.inspectPlaylist(playlistUrl.trim());
                }}
                className="playlist-form"
              >
                <label className="field" htmlFor="playlist-url">
                  <span className="small">{t.playlistUrl}</span>
                  <input
                    id="playlist-url"
                    type="url"
                    inputMode="url"
                    required
                    value={playlistUrl}
                    onChange={(event) => {
                      setPlaylistUrl(event.target.value);
                      c.clearPlaylist();
                    }}
                    aria-describedby="playlist-feedback"
                  />
                </label>
                <button
                  type="submit"
                  className="button secondary"
                  disabled={c.playlistBusy || c.cooldownSeconds > 0}
                >
                  <BusyLabel busy={c.playlistBusy}>
                    {c.playlistBusy ? t.playlistBusy : t.playlistInspect}
                  </BusyLabel>
                </button>
              </form>
              <div id="playlist-feedback">
                <ErrorNotice error={c.errors.playlist} locale={locale} />
              </div>
              {c.playlist ? (
                <>
                  <p className="small muted wrap-anywhere">{c.playlist.canonical_url}</p>
                  {c.playlist.stopped_at_cap || c.playlist.limited ? (
                    <p className="small muted">{t.playlistLimited}</p>
                  ) : null}
                  <ol className="playlist-entries">
                    {c.playlist.entries.map((entry) => (
                      <li key={entry.position}>
                        <span className="small muted numeric">{entry.position}</span>
                        <span className="playlist-entry-title">
                          {entry.title || entry.video_id || t.playlistUnavailable}
                        </span>
                        {entry.available && entry.canonical_url ? (
                          <button
                            type="button"
                            className="button secondary"
                            onClick={() => {
                              c.selectPlaylist(entry.canonical_url!);
                              setConsentFor(null);
                              focusUrl();
                            }}
                          >
                            {t.playlistUse}
                          </button>
                        ) : (
                          <span className="small muted">{t.playlistUnavailable}</span>
                        )}
                      </li>
                    ))}
                  </ol>
                  {!c.playlist.entries.length ? (
                    <p className="small muted">{t.playlistEmpty}</p>
                  ) : null}
                </>
              ) : null}
            </details>
          ) : null}
        </>
      ) : null}
      <footer className="app-footer">
        <p>
          {t.notice}{" "}
          <a
            className="text-link"
            href="https://www.youtube.com/static?template=terms"
            target="_blank"
            rel="noreferrer"
          >
            {t.terms}
          </a>
        </p>
        <a
          className="text-link"
          href={`https://support.google.com/youtube/answer/56100?hl=${locale}`}
          target="_blank"
          rel="noreferrer"
        >
          {t.ownUploads} ↗
        </a>
      </footer>
    </main>
  );
}
