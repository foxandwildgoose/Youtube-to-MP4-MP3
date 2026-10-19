import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import {
  api,
  ApiError,
  asApiError,
  type Analysis,
  type Job,
  type PlaylistInspection,
  type Readiness,
  type RequestOptions,
  type Session,
  type Settings,
} from "./api";
import { activeJobs, mergeJobs, orderedJobs, removeJob, type JobEntities } from "./job-store";
import { JobFeed, type FeedState } from "./job-feed";
import { SessionScope } from "./session";
import { SessionRequests } from "./session-requests";
import {
  localPreferences,
  persistPreferences,
  PreferenceWriter,
  type Preferences,
} from "./preferences";
import {
  AnalysisGeneration,
  readIntent,
  sameRequest,
  writeIntent,
  type SubmissionIntent,
} from "./submission";
export type Gate = "boot" | "offline" | "setup" | "login" | "ready";
type Area =
  | "auth"
  | "analyze"
  | "create"
  | "history"
  | "preferences"
  | "playlist"
  | "diagnostics"
  | "connection";
type Errors = Record<Area, ApiError | null> & { jobs: Record<string, ApiError> };
const emptyErrors = (): Errors => ({
  auth: null,
  analyze: null,
  create: null,
  history: null,
  preferences: null,
  playlist: null,
  diagnostics: null,
  connection: null,
  jobs: {},
});
export type HistoryOptions = {
  search?: string;
  format?: string;
  status?: string;
  file_state?: string;
  offset?: number;
};
export type JobAction = "cancel" | "retain" | "deleteFile" | "deleteHistory";
function localStorageSafe(): Storage | undefined {
  try {
    return typeof window === "undefined" ? undefined : window.localStorage;
  } catch {
    return undefined;
  }
}
function sessionStorageSafe(): Storage | undefined {
  try {
    return typeof window === "undefined" ? undefined : window.sessionStorage;
  } catch {
    return undefined;
  }
}
export function useDownloaderController() {
  const [gate, setGate] = useState<Gate>("boot");
  const [session, setSession] = useState<Session | null>(null);
  const [settings, setSettings] = useState<Settings | null>(null);
  const [readiness, setReadiness] = useState<Readiness | null>(null);
  const [prefs, setPrefs] = useState<Preferences>(() => localPreferences(localStorageSafe()));
  // Hydration starts with server labels; stored values are already read before persistence.
  const [clientReady, setClientReady] = useState(false);
  const prefsRef = useRef(prefs);
  prefsRef.current = prefs;
  const preferencesRevision = useRef(0);
  const preferenceWriter = useRef(new PreferenceWriter());
  const [errors, setErrors] = useState<Errors>(emptyErrors);
  const [retryDeadline, setRetryDeadline] = useState(0);
  const retryDeadlineRef = useRef(0);
  const [url, setDraftUrl] = useState("");
  const urlRef = useRef(url);
  urlRef.current = url;
  const [analysis, setAnalysis] = useState<Analysis | null>(null);
  const acceptedAnalysis = useRef<Analysis | null>(null);
  const analysisGeneration = useRef(new AnalysisGeneration());
  const playlistGeneration = useRef(new AnalysisGeneration());
  const [analysisBusy, setAnalysisBusy] = useState(false);
  const [submitting, setSubmitting] = useState(false);
  const submissionLock = useRef(false);
  const [authBusy, setAuthBusy] = useState(false);
  const authLock = useRef(false);
  const [playlistBusy, setPlaylistBusy] = useState(false);
  const [preferencesBusy, setPreferencesBusy] = useState(false);
  const [playlist, setPlaylist] = useState<PlaylistInspection | null>(null);
  const [parentId, setParentId] = useState<string | null>(null);
  const [entities, setEntities] = useState<JobEntities>(() => new Map());
  const entitiesRef = useRef(entities);
  entitiesRef.current = entities;
  const [historyIds, setHistoryIds] = useState<string[]>([]);
  const [historyTotal, setHistoryTotal] = useState(0);
  const [historyLoading, setHistoryLoading] = useState(false);
  const [historyCriteria, setHistoryCriteria] = useState({
    search: "",
    format: "",
    status: "",
    file_state: "",
    offset: 0,
  });
  const criteriaRef = useRef(historyCriteria);
  criteriaRef.current = historyCriteria;
  const historyGeneration = useRef(0);
  const [pendingJobs, setPendingJobs] = useState<Record<string, boolean>>({});
  const jobLocks = useRef(new Set<string>());
  const [live, setLive] = useState<FeedState>("polling");
  const [pendingIntent, setPendingIntent] = useState<SubmissionIntent | null>(() =>
    readIntent(sessionStorageSafe()),
  );
  const intentRef = useRef(pendingIntent);
  intentRef.current = pendingIntent;
  const [diagnosticsBusy, setDiagnosticsBusy] = useState(false);
  const diagnosticsLock = useRef(false);
  const [diagnosticsValue, setDiagnosticsValue] = useState<Record<string, unknown> | null>(null);
  const [now, setNow] = useState(Date.now);
  const sessionRef = useRef<Session | null>(null);
  const requestScope = useRef(new SessionScope());
  const feed = useRef<JobFeed | null>(null);
  const connectGeneration = useRef(0);
  const previousActiveIds = useRef(new Set<string>());
  const merge = useCallback(
    (jobs: Job[]) => setEntities((current) => mergeJobs(current, jobs)),
    [],
  );
  const clearError = useCallback(
    (area: Area | "jobs") =>
      setErrors((current) => ({ ...current, [area]: area === "jobs" ? {} : null })),
    [],
  );
  const report = useCallback((area: Area, error: unknown) => {
    const problem = asApiError(error);
    if (problem.retryAt && problem.retryAt > retryDeadlineRef.current) {
      retryDeadlineRef.current = problem.retryAt;
      setRetryDeadline(problem.retryAt);
    }
    if (problem.code !== "ABORTED") setErrors((current) => ({ ...current, [area]: problem }));
    return problem;
  }, []);
  const saveIntent = useCallback((intent: SubmissionIntent | null) => {
    intentRef.current = intent;
    setPendingIntent(intent);
    writeIntent(sessionStorageSafe(), intent);
  }, []);
  const clearSession = useCallback((problem?: ApiError, nextGate: Gate = "login") => {
    requestScope.current.reset();
    connectGeneration.current += 1;
    feed.current?.stop();
    feed.current = null;
    analysisGeneration.current.invalidate();
    playlistGeneration.current.invalidate();
    preferenceWriter.current.invalidate();
    sessionRef.current = null;
    setSession(null);
    setGate(nextGate);
    setSettings(null);
    setReadiness(null);
    setEntities(new Map());
    setHistoryIds([]);
    setHistoryTotal(0);
    setHistoryLoading(false);
    setPreferencesBusy(false);
    historyGeneration.current += 1;
    acceptedAnalysis.current = null;
    setAnalysis(null);
    setAnalysisBusy(false);
    setPlaylist(null);
    setPlaylistBusy(false);
    setParentId(null);
    setDiagnosticsValue(null);
    setErrors({
      ...emptyErrors(),
      [nextGate === "offline" ? "connection" : "auth"]: problem || null,
    });
    setPendingJobs({});
    jobLocks.current.clear();
    setLive("polling");
  }, []);
  const sessionRequests = useMemo(
    () =>
      new SessionRequests({
        scope: requestScope.current,
        current: () => sessionRef.current,
        refresh: (signal) => api.session({ signal }),
        accept: (fresh) => {
          sessionRef.current = fresh;
          setSession(fresh);
        },
        expired: (problem, previous) =>
          clearSession(problem, previous.password_required === false ? "offline" : "login"),
        refreshError: (problem) => report("connection", problem),
      }),
    [clearSession, report],
  );
  const withAuth = useCallback(
    async <T>(
      operation: (csrf: string, options: RequestOptions) => Promise<T>,
      signal?: AbortSignal,
    ): Promise<T> => {
      return sessionRequests.run(operation, signal);
    },
    [sessionRequests],
  );
  const retryConnection = useCallback(
    async (showBusy = true) => {
      const generation = ++connectGeneration.current;
      if (showBusy) setGate((current) => (current === "ready" ? current : "boot"));
      clearError("connection");
      try {
        const previous = sessionRef.current;
        const current =
          previous?.authenticated && previous.password_required === false
            ? await sessionRequests.renew(previous)
            : await requestScope.current.run((signal) => api.session({ signal }));
        if (generation !== connectGeneration.current) return;
        if (!current.authenticated && previous?.authenticated)
          clearSession(undefined, current.password_required === false ? "offline" : "login");
        sessionRef.current = current;
        setSession(current);
        setGate(
          current.authenticated
            ? "ready"
            : current.password_required === false
              ? "offline"
              : current.bootstrapped
                ? "login"
                : "setup",
        );
      } catch (error) {
        if (generation === connectGeneration.current) {
          report("connection", error);
          setGate("offline");
        }
      }
    },
    [clearError, clearSession, report, sessionRequests],
  );
  const refreshStorage = useCallback(async () => {
    try {
      const started = preferencesRevision.current;
      const value = await withAuth((csrf, options) => api.settings(csrf, options));
      setSettings(value);
      if (started === preferencesRevision.current) {
        prefsRef.current = value;
        setPrefs({ language: value.language, theme: value.theme, mp3_bitrate: value.mp3_bitrate });
      }
      const readinessValue = await withAuth((csrf, options) => api.readiness(csrf, options));
      setReadiness(readinessValue);
    } catch (error) {
      report("preferences", error);
    }
  }, [withAuth, report]);
  const loadHistory = useCallback(
    async (options: HistoryOptions = {}) => {
      const generation = ++historyGeneration.current;
      const criteria = { ...criteriaRef.current, ...options };
      criteriaRef.current = criteria;
      setHistoryCriteria(criteria);
      setHistoryLoading(true);
      clearError("history");
      try {
        let result = await withAuth((csrf, requestOptions) =>
          api.jobs(csrf, { active: false, limit: 20, ...criteria }, requestOptions),
        );
        if (
          generation === historyGeneration.current &&
          !result.jobs.length &&
          result.total > 0 &&
          criteria.offset >= result.total
        ) {
          criteria.offset = Math.floor((result.total - 1) / 20) * 20;
          criteriaRef.current = criteria;
          setHistoryCriteria({ ...criteria });
          result = await withAuth((csrf, requestOptions) =>
            api.jobs(csrf, { active: false, limit: 20, ...criteria }, requestOptions),
          );
        }
        merge(result.jobs);
        if (generation === historyGeneration.current) {
          setHistoryIds(result.jobs.map((job) => job.id));
          setHistoryTotal(result.total);
        }
      } catch (error) {
        if (generation === historyGeneration.current) report("history", error);
      } finally {
        if (generation === historyGeneration.current) setHistoryLoading(false);
      }
    },
    [clearError, merge, report, withAuth],
  );
  useEffect(() => {
    void retryConnection();
    return () => {
      connectGeneration.current += 1;
    };
  }, [retryConnection]);
  useEffect(() => {
    setClientReady(true);
  }, []);
  useEffect(() => {
    persistPreferences(prefs, localStorageSafe());
    document.documentElement.lang = prefs.language;
    const media = window.matchMedia("(prefers-color-scheme: dark)");
    const apply = () => {
      document.documentElement.dataset.theme =
        prefs.theme === "dark" || (prefs.theme === "system" && media.matches) ? "dark" : "light";
    };
    apply();
    media.addEventListener("change", apply);
    return () => media.removeEventListener("change", apply);
  }, [prefs]);
  useEffect(() => {
    const timer = setInterval(() => setNow(Date.now()), 1000);
    return () => clearInterval(timer);
  }, []);
  const csrf = session?.authenticated ? session.csrf_token : "";
  useEffect(() => {
    if (gate !== "ready" || !csrf) return;
    void refreshStorage();
    void loadHistory();
    let cycles = 0;
    const manager = new JobFeed({
      discover: async (signal) => {
        const result = await withAuth(
          (token, options) => api.jobs(token, { active: true, limit: 100 }, options),
          signal,
        );
        cycles += 1;
        if (cycles % 6 === 0) {
          void loadHistory();
          void refreshStorage();
        }
        return result.jobs;
      },
      accept: merge,
      state: setLive,
      error: (error) => report("connection", error),
      expired: () => {
        if (sessionRef.current?.password_required === false) void retryConnection(false);
        else clearSession(new ApiError({ status: 401, code: "UNAUTHORIZED", action: "login" }));
      },
    });
    feed.current = manager;
    manager.start();
    const recover = () => {
      if (document.visibilityState === "visible") {
        manager.refresh();
        void loadHistory();
        void refreshStorage();
      }
    };
    const online = () => {
      manager.setOnline(true);
      recover();
    };
    const offline = () => manager.setOnline(false);
    window.addEventListener("focus", recover);
    document.addEventListener("visibilitychange", recover);
    window.addEventListener("online", online);
    window.addEventListener("offline", offline);
    return () => {
      manager.stop();
      if (feed.current === manager) feed.current = null;
      window.removeEventListener("focus", recover);
      document.removeEventListener("visibilitychange", recover);
      window.removeEventListener("online", online);
      window.removeEventListener("offline", offline);
    };
  }, [
    gate,
    csrf,
    clearSession,
    loadHistory,
    merge,
    refreshStorage,
    report,
    retryConnection,
    withAuth,
  ]);
  useEffect(() => {
    const current = activeJobs(entities);
    feed.current?.sync(current);
    const completed = [...previousActiveIds.current].some((id) => {
      const job = entities.get(id);
      return job && job.status !== "queued" && job.status !== "running";
    });
    previousActiveIds.current = new Set(current.map((job) => job.id));
    if (completed) {
      void loadHistory();
      void refreshStorage();
    }
  }, [entities, loadHistory, refreshStorage]);
  useEffect(() => {
    if (gate === "ready") return;
    const recover = () => {
      if (document.visibilityState === "visible") void retryConnection(false);
    };
    window.addEventListener("online", recover);
    window.addEventListener("focus", recover);
    document.addEventListener("visibilitychange", recover);
    return () => {
      window.removeEventListener("online", recover);
      window.removeEventListener("focus", recover);
      document.removeEventListener("visibilitychange", recover);
    };
  }, [gate, retryConnection]);
  useEffect(() => {
    if (!session?.authenticated) return;
    const delay = Math.max(0, Date.parse(session.expires_at) - Date.now());
    const timer = setTimeout(
      () => {
        void retryConnection(false);
      },
      Math.min(delay + 100, 2147483647),
    );
    return () => clearTimeout(timer);
  }, [session, retryConnection]);
  useEffect(
    () => () => {
      requestScope.current.reset();
      analysisGeneration.current.invalidate();
      playlistGeneration.current.invalidate();
      preferenceWriter.current.invalidate();
      feed.current?.stop();
    },
    [],
  );
  const login = useCallback(
    async (password: string) => {
      if (authLock.current) return;
      authLock.current = true;
      setAuthBusy(true);
      clearError("auth");
      try {
        const next = await requestScope.current.run((signal) => api.login(password, { signal }));
        if (!next.authenticated) throw new ApiError({ code: "UNAUTHORIZED", status: 401 });
        sessionRef.current = next;
        setSession(next);
        setGate("ready");
      } catch (error) {
        report("auth", error);
      } finally {
        authLock.current = false;
        setAuthBusy(false);
      }
    },
    [clearError, report],
  );
  const bootstrap = useCallback(
    async (password: string) => {
      if (authLock.current) return;
      authLock.current = true;
      setAuthBusy(true);
      clearError("auth");
      try {
        await requestScope.current.run((signal) => api.bootstrap(password, { signal }));
        const next = await requestScope.current.run((signal) => api.login(password, { signal }));
        sessionRef.current = next;
        setSession(next);
        setGate(next.authenticated ? "ready" : "login");
      } catch (error) {
        report("auth", error);
      } finally {
        authLock.current = false;
        setAuthBusy(false);
      }
    },
    [clearError, report],
  );
  const logout = useCallback(async () => {
    if (authLock.current) return;
    authLock.current = true;
    setAuthBusy(true);
    clearError("auth");
    try {
      await withAuth((token, options) => api.logout(token, options));
      clearSession();
    } catch (error) {
      report("auth", error);
    } finally {
      authLock.current = false;
      setAuthBusy(false);
    }
  }, [clearError, clearSession, report, withAuth]);
  const setUrl = useCallback(
    (next: string) => {
      if (next !== urlRef.current) {
        analysisGeneration.current.invalidate();
        acceptedAnalysis.current = null;
        setAnalysis(null);
        setAnalysisBusy(false);
        clearError("analyze");
        clearError("create");
      }
      urlRef.current = next;
      setDraftUrl(next);
    },
    [clearError],
  );
  const analyze = useCallback(
    async (nextUrl?: string) => {
      if (Date.now() < retryDeadlineRef.current) return null;
      const draft = (nextUrl ?? urlRef.current).trim();
      if (nextUrl !== undefined && nextUrl !== urlRef.current) {
        urlRef.current = nextUrl;
        setDraftUrl(nextUrl);
      }
      const generation = analysisGeneration.current.begin();
      acceptedAnalysis.current = null;
      setAnalysis(null);
      setAnalysisBusy(true);
      clearError("analyze");
      clearError("create");
      try {
        const result = await withAuth(
          (token, options) => api.analyze(draft, token, prefsRef.current.language, options),
          generation.signal,
        );
        if (!generation.current() || draft !== urlRef.current.trim()) return null;
        if (
          parentId &&
          entitiesRef.current.get(parentId)?.source.video_id !== result.source.video_id
        )
          setParentId(null);
        acceptedAnalysis.current = result;
        setAnalysis(result);
        return result;
      } catch (error) {
        if (generation.current()) report("analyze", error);
        return null;
      } finally {
        if (generation.current()) setAnalysisBusy(false);
      }
    },
    [clearError, parentId, report, withAuth],
  );
  const replaySubmission = useCallback(async () => {
    const intent = intentRef.current;
    if (!intent || submissionLock.current || Date.now() < retryDeadlineRef.current) return null;
    submissionLock.current = true;
    setSubmitting(true);
    clearError("create");
    try {
      const job = await withAuth((token, options) =>
        intent.parentId
          ? api.retryJob(
              token,
              prefsRef.current.language,
              intent.parentId,
              intent.key,
              intent.body,
              options,
            )
          : api.createJob(token, prefsRef.current.language, intent.key, intent.body, options),
      );
      merge([job]);
      saveIntent(null);
      setParentId(null);
      feed.current?.refresh();
      void loadHistory();
      void refreshStorage();
      return job;
    } catch (error) {
      const problem = report("create", error);
      // Definitive client rejection permits a corrected request; transport/5xx/auth remain unresolved.
      if (
        problem.status !== null &&
        problem.status >= 400 &&
        problem.status < 500 &&
        ![401, 403, 408, 429].includes(problem.status)
      )
        saveIntent(null);
      return null;
    } finally {
      submissionLock.current = false;
      setSubmitting(false);
    }
  }, [clearError, loadHistory, merge, refreshStorage, report, saveIntent, withAuth]);
  const create = useCallback(
    async (choiceId: string, keep: boolean, consent: boolean) => {
      if (submissionLock.current || Date.now() < retryDeadlineRef.current) return null;
      const analysis = acceptedAnalysis.current;
      const choice = analysis?.choices.find((item) => item.choice_id === choiceId);
      if (!analysis || !choice || Date.parse(analysis.expires_at) <= Date.now()) {
        report("create", new ApiError({ code: "ANALYSIS_EXPIRED", action: "reanalyze" }));
        return null;
      }
      if (choice.requires_consent && !consent) {
        report("create", new ApiError({ code: "CONSENT_REQUIRED", action: "consent" }));
        return null;
      }
      const body = {
        analysis_id: analysis.analysis_id,
        choice_id: choiceId,
        keep_on_server: keep,
        conversion_consent: consent,
      };
      const previous = intentRef.current;
      if (previous && !sameRequest(previous, body, parentId)) {
        report("create", new ApiError({ code: "SUBMISSION_UNRESOLVED", action: "replay" }));
        return null;
      }
      if (!previous)
        saveIntent({
          key: crypto.randomUUID(),
          body,
          parentId,
          videoId: analysis.source.video_id,
          title: analysis.source.title,
          createdAt: Date.now(),
        });
      return replaySubmission();
    },
    [parentId, replaySubmission, report, saveIntent],
  );
  const mutateJob = useCallback(
    async (action: JobAction, id: string, keep?: boolean) => {
      const key = `${id}:${action}`;
      if (jobLocks.current.has(key)) return;
      jobLocks.current.add(key);
      setPendingJobs((current) => ({ ...current, [key]: true }));
      setErrors((current) => {
        const jobs = { ...current.jobs };
        delete jobs[id];
        return { ...current, jobs };
      });
      try {
        if (action === "deleteHistory") {
          await withAuth((token, options) => api.deleteHistory(token, id, options));
          setEntities((current) => removeJob(current, id));
          setHistoryIds((current) => current.filter((item) => item !== id));
        } else {
          const job = await withAuth((token, options) =>
            action === "cancel"
              ? api.cancel(token, id, options)
              : action === "retain"
                ? api.retention(token, id, Boolean(keep), options)
                : api.deleteFile(token, id, options),
          );
          merge([job]);
        }
        await loadHistory();
        await refreshStorage();
        feed.current?.refresh();
      } catch (error) {
        const problem = asApiError(error);
        if (problem.code !== "ABORTED")
          setErrors((current) => ({ ...current, jobs: { ...current.jobs, [id]: problem } }));
      } finally {
        jobLocks.current.delete(key);
        setPendingJobs((current) => {
          const next = { ...current };
          delete next[key];
          return next;
        });
      }
    },
    [loadHistory, merge, refreshStorage, withAuth],
  );
  const savePreferences = useCallback(
    async (patch: Partial<Preferences>) => {
      preferencesRevision.current += 1;
      const revision = preferencesRevision.current;
      const next = { ...prefsRef.current, ...patch };
      prefsRef.current = next;
      setPrefs(next);
      clearError("preferences");
      if (!sessionRef.current?.authenticated) {
        setPreferencesBusy(false);
        return;
      }
      setPreferencesBusy(true);
      try {
        await preferenceWriter.current.save(
          () => withAuth((token, options) => api.patchSettings(token, next, options)),
          (value) => {
            setSettings(value);
            prefsRef.current = value;
            setPrefs({
              language: value.language,
              theme: value.theme,
              mp3_bitrate: value.mp3_bitrate,
            });
          },
        );
      } catch (error) {
        if (revision === preferencesRevision.current) report("preferences", error);
      } finally {
        if (revision === preferencesRevision.current) setPreferencesBusy(false);
      }
    },
    [clearError, report, withAuth],
  );
  const inspectPlaylist = useCallback(
    async (playlistUrl: string) => {
      if (Date.now() < retryDeadlineRef.current) return;
      const generation = playlistGeneration.current.begin();
      setPlaylistBusy(true);
      setPlaylist(null);
      clearError("playlist");
      try {
        const result = await withAuth(
          (token, options) => api.playlist(token, prefsRef.current.language, playlistUrl, options),
          generation.signal,
        );
        if (generation.current()) setPlaylist(result);
      } catch (error) {
        if (generation.current()) report("playlist", error);
      } finally {
        if (generation.current()) setPlaylistBusy(false);
      }
    },
    [clearError, report, withAuth],
  );
  const download = useCallback(
    async (job: Job) => {
      const key = `${job.id}:download`;
      if (jobLocks.current.has(key)) return false;
      jobLocks.current.add(key);
      setPendingJobs((current) => ({ ...current, [key]: true }));
      try {
        await withAuth((token, options) => api.checkFile(token, job.id, options));
        const link = document.createElement("a");
        link.href = `/api/v1/jobs/${encodeURIComponent(job.id)}/file`;
        link.download = job.artifact?.filename || "";
        link.target = "_blank";
        link.rel = "noopener";
        document.body.append(link);
        link.click();
        link.remove();
        return true;
      } catch (error) {
        const problem = asApiError(error);
        if (problem.code !== "ABORTED")
          setErrors((current) => ({ ...current, jobs: { ...current.jobs, [job.id]: problem } }));
        void loadHistory();
        return false;
      } finally {
        jobLocks.current.delete(key);
        setPendingJobs((current) => {
          const next = { ...current };
          delete next[key];
          return next;
        });
      }
    },
    [loadHistory, withAuth],
  );
  const diagnostics = useCallback(async () => {
    if (diagnosticsLock.current) return;
    diagnosticsLock.current = true;
    setDiagnosticsBusy(true);
    clearError("diagnostics");
    try {
      setDiagnosticsValue(await withAuth((token, options) => api.diagnostics(token, options)));
    } catch (error) {
      report("diagnostics", error);
    } finally {
      diagnosticsLock.current = false;
      setDiagnosticsBusy(false);
    }
  }, [clearError, report, withAuth]);
  const jobs = useMemo(() => orderedJobs(entities), [entities]);
  const active = useMemo(() => activeJobs(entities), [entities]);
  const history = useMemo(
    () => historyIds.map((id) => entities.get(id)).filter((job): job is Job => Boolean(job)),
    [historyIds, entities],
  );
  return {
    gate,
    session,
    settings,
    readiness,
    processingReady: readiness?.processing_ready ?? null,
    locale: clientReady ? prefs.language : ("ko" as const),
    theme: clientReady ? prefs.theme : ("system" as const),
    mp3Bitrate: prefs.mp3_bitrate,
    errors,
    clearError,
    url,
    setUrl,
    analysis,
    analysisExpired: Boolean(analysis && Date.parse(analysis.expires_at) <= now),
    analysisBusy,
    submitting,
    authBusy,
    playlistBusy,
    preferencesBusy,
    parentId,
    jobs,
    active,
    history,
    historyTotal,
    historyOffset: historyCriteria.offset,
    historyQuery: historyCriteria.search,
    historyFormat: historyCriteria.format,
    historyLimit: 20,
    historyStatus: historyCriteria.status,
    historyFileState: historyCriteria.file_state,
    historyLoading,
    pendingJobs,
    live,
    pendingIntent,
    playlist,
    diagnosticsValue,
    diagnosticsBusy,
    cooldownSeconds: Math.max(0, Math.ceil((retryDeadline - now) / 1000)),
    retryConnection,
    login,
    bootstrap,
    logout,
    analyze,
    create,
    replaySubmission,
    discardSubmission: () => {
      if (!submissionLock.current) saveIntent(null);
    },
    cancelAnalysis: () => {
      analysisGeneration.current.invalidate();
      setAnalysisBusy(false);
    },
    resetAnalysis: () => {
      analysisGeneration.current.invalidate();
      acceptedAnalysis.current = null;
      setAnalysis(null);
      setAnalysisBusy(false);
    },
    prepareRetry: (job: Job) => {
      analysisGeneration.current.invalidate();
      acceptedAnalysis.current = null;
      setAnalysis(null);
      setAnalysisBusy(false);
      setParentId(["failed", "cancelled", "interrupted"].includes(job.status) ? job.id : null);
      setUrl(job.source.canonical_url || "");
    },
    clearRetry: () => setParentId(null),
    mutateJob,
    loadHistory,
    savePreferences,
    refreshStorage,
    download,
    inspectPlaylist,
    clearPlaylist: () => {
      playlistGeneration.current.invalidate();
      setPlaylist(null);
      setPlaylistBusy(false);
    },
    selectPlaylist: (next: string) => {
      setParentId(null);
      setUrl(next);
    },
    diagnostics,
  };
}
