import { asApiError, type ApiError } from "./api.ts";
import { isJob, type Job } from "./contracts.ts";
import { isActive } from "./job-store.ts";
export type FeedState = "connecting" | "live" | "reconnecting" | "polling" | "offline";
type Source = {
  close: () => void;
  addEventListener: (type: string, listener: (event: MessageEvent) => void) => void;
};
export type FeedOptions = {
  discover: (signal: AbortSignal) => Promise<Job[]>;
  accept: (jobs: Job[]) => void;
  error: (error: ApiError) => void;
  state: (state: FeedState) => void;
  expired: () => void;
  source?: (url: string) => Source;
  pollMs?: number;
  now?: () => number;
};
/** A session owns at most two streams; recurring polling discovers every active job. */
export class JobFeed {
  private options: FeedOptions;
  private sources = new Map<string, { source: Source; open: boolean }>();
  private blocked = new Map<string, number>();
  private jobs: Job[] = [];
  private timer: ReturnType<typeof setTimeout> | null = null;
  private request: AbortController | null = null;
  private stopped = true;
  private offline = false;
  private reconnecting = false;
  private now: () => number;
  constructor(options: FeedOptions) {
    this.options = options;
    this.now = options.now || Date.now;
  }
  start(): void {
    if (!this.stopped) return;
    this.stopped = false;
    this.refresh();
  }
  stop(): void {
    this.stopped = true;
    if (this.timer) clearTimeout(this.timer);
    this.timer = null;
    this.request?.abort();
    this.request = null;
    for (const { source } of this.sources.values()) source.close();
    this.sources.clear();
    this.blocked.clear();
  }
  setOnline(online: boolean): void {
    this.offline = !online;
    if (!online) {
      for (const { source } of this.sources.values()) source.close();
      this.sources.clear();
      this.emitState();
    } else {
      this.blocked.clear();
      this.refresh();
    }
  }
  sync(jobs: Job[]): void {
    this.jobs = jobs.filter(isActive);
    this.reconcile();
  }
  refresh(): void {
    if (!this.stopped && !this.request) void this.poll();
  }
  private emitState(): void {
    if (this.stopped) return;
    const live = [...this.sources.values()].some((value) => value.open);
    this.options.state(
      this.offline
        ? "offline"
        : live
          ? "live"
          : this.sources.size
            ? this.reconnecting
              ? "reconnecting"
              : "connecting"
            : "polling",
    );
  }
  private reconcile(): void {
    if (this.stopped || this.offline) return;
    const active = new Set(this.jobs.map((job) => job.id));
    for (const [id, { source }] of this.sources)
      if (!active.has(id)) {
        source.close();
        this.sources.delete(id);
      }
    for (const job of this.jobs) {
      if (this.sources.size >= 2) break;
      if (this.sources.has(job.id) || (this.blocked.get(job.id) || 0) > this.now()) continue;
      const source =
        this.options.source?.(`/api/v1/jobs/${encodeURIComponent(job.id)}/events`) ||
        new EventSource(`/api/v1/jobs/${encodeURIComponent(job.id)}/events`);
      this.sources.set(job.id, { source, open: false });
      const close = () => {
        if (this.stopped || this.sources.get(job.id)?.source !== source) return;
        source.close();
        this.sources.delete(job.id);
        this.blocked.set(job.id, this.now() + 10000);
        this.reconnecting = true;
        this.emitState();
        this.refresh();
      };
      source.addEventListener("open", () => {
        if (this.stopped || this.sources.get(job.id)?.source !== source) return;
        const entry = this.sources.get(job.id);
        if (entry) entry.open = true;
        this.reconnecting = false;
        this.emitState();
      });
      source.addEventListener("snapshot", (event) => {
        if (this.stopped || this.sources.get(job.id)?.source !== source) return;
        try {
          const data: unknown = JSON.parse(
            String((event as MessageEvent).data).slice(0, 2 * 1024 * 1024),
          );
          if (!isJob(data) || data.id !== job.id) {
            close();
            return;
          }
          this.options.accept([data]);
          if (!isActive(data)) {
            source.close();
            this.sources.delete(job.id);
            this.jobs = this.jobs.filter((item) => item.id !== job.id);
            this.reconcile();
          }
        } catch {
          close();
        }
      });
      source.addEventListener("bye", (event) => {
        if (this.stopped || this.sources.get(job.id)?.source !== source) return;
        try {
          const data = JSON.parse(String((event as MessageEvent).data)) as {
            authenticated?: boolean;
          };
          if (data.authenticated === false) {
            this.options.expired();
            this.stop();
            return;
          }
        } catch {
          /* A malformed bye still falls back to polling. */
        }
        close();
      });
      source.addEventListener("error", close);
    }
    this.emitState();
  }
  private async poll(): Promise<void> {
    if (this.stopped || this.offline || this.request) return;
    if (this.timer) clearTimeout(this.timer);
    const request = new AbortController();
    this.request = request;
    try {
      const jobs = await this.options.discover(request.signal);
      if (this.stopped || request.signal.aborted) return;
      this.options.accept(jobs);
      this.reconcile();
    } catch (error) {
      if (!this.stopped && !request.signal.aborted) {
        const problem = asApiError(error);
        this.options.error(problem);
        if (problem.status === 401) {
          this.options.expired();
          this.stop();
        } else this.emitState();
      }
    } finally {
      if (this.request === request) this.request = null;
      if (!this.stopped && !this.offline)
        this.timer = setTimeout(() => this.refresh(), this.options.pollMs ?? 2500);
    }
  }
}
