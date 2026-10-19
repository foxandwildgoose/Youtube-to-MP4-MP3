import type { JobRequest } from "./contracts.ts";
export type SubmissionIntent = {
  key: string;
  body: JobRequest;
  parentId: string | null;
  videoId: string;
  title: string;
  createdAt: number;
};
export type IntentStorage = Pick<Storage, "getItem" | "setItem" | "removeItem">;
const STORAGE_KEY = "seorap-pending-submission-v1";
export function readIntent(storage?: IntentStorage): SubmissionIntent | null {
  try {
    const parsed = JSON.parse(storage?.getItem(STORAGE_KEY) || "null") as SubmissionIntent | null;
    if (
      parsed &&
      typeof parsed.key === "string" &&
      parsed.key.length <= 200 &&
      typeof parsed.videoId === "string" &&
      typeof parsed.title === "string" &&
      typeof parsed.createdAt === "number" &&
      (parsed.parentId === null || typeof parsed.parentId === "string") &&
      typeof parsed.body?.analysis_id === "string" &&
      typeof parsed.body.choice_id === "string" &&
      typeof parsed.body.keep_on_server === "boolean" &&
      typeof parsed.body.conversion_consent === "boolean"
    )
      return parsed;
  } catch {
    /* Storage can be denied by the browser. In-memory intent still works. */
  }
  return null;
}
export function writeIntent(
  storage: IntentStorage | undefined,
  intent: SubmissionIntent | null,
): void {
  try {
    if (intent) storage?.setItem(STORAGE_KEY, JSON.stringify(intent));
    else storage?.removeItem(STORAGE_KEY);
  } catch {
    /* Keep in memory if persistence is unavailable. */
  }
}
export function sameRequest(
  intent: SubmissionIntent,
  body: JobRequest,
  parentId: string | null,
): boolean {
  return (
    intent.parentId === parentId &&
    intent.body.analysis_id === body.analysis_id &&
    intent.body.choice_id === body.choice_id &&
    intent.body.keep_on_server === body.keep_on_server &&
    intent.body.conversion_consent === body.conversion_consent
  );
}
/** Invalidating a generation prevents late results even when transport ignores abort. */
export class AnalysisGeneration {
  private generation = 0;
  private controller: AbortController | null = null;
  invalidate(): void {
    this.generation += 1;
    this.controller?.abort();
    this.controller = null;
  }
  begin(): { signal: AbortSignal; current: () => boolean } {
    this.invalidate();
    const generation = this.generation;
    this.controller = new AbortController();
    return { signal: this.controller.signal, current: () => this.generation === generation };
  }
}
