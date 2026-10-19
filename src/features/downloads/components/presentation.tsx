import { useEffect, useState, type ReactNode } from "react";
import { AlertCircle, LoaderCircle } from "lucide-react";
import { localizedError, translate, type Locale } from "../i18n";

export function BusyLabel({ busy, children }: { busy: boolean; children: ReactNode }) {
  return (
    <>
      {busy ? <LoaderCircle className="icon spin" aria-hidden="true" /> : null}
      <span>{children}</span>
    </>
  );
}
export type DisplayError = {
  code?: string;
  status?: number | null;
  retryAt?: number | null;
  retryAfterSeconds?: number | null;
  retry_after_seconds?: number;
  retryable?: boolean;
};
export function ErrorNotice({
  error,
  locale,
  id,
  onRetry,
  retryLabel,
}: {
  error: DisplayError | null | undefined;
  locale: Locale;
  id?: string;
  onRetry?: () => void;
  retryLabel?: string;
}) {
  const [now, setNow] = useState(() => Date.now());
  const deadline = error?.retryAt;
  useEffect(() => {
    if (!deadline || deadline <= Date.now()) return;
    const timer = window.setInterval(() => setNow(Date.now()), 1000);
    return () => window.clearInterval(timer);
  }, [deadline]);
  if (!error) return null;
  const t = translate(locale);
  const wait = deadline
    ? Math.max(0, Math.ceil((deadline - now) / 1000))
    : (error.retryAfterSeconds ?? error.retry_after_seconds ?? 0);
  return (
    <div id={id} className="error-note" role="alert">
      <AlertCircle className="icon" aria-hidden="true" />
      <div>
        <p>{localizedError(error.code, locale)}</p>
        {wait > 0 ? (
          <p className="small numeric">
            {t.retryAfter} {wait} {t.seconds}
          </p>
        ) : null}
        {error.status || error.code ? (
          <p className="small muted">
            {t.errorCode}: {error.code || `HTTP ${error.status}`}
            {error.code && error.status ? ` · HTTP ${error.status}` : ""}
          </p>
        ) : null}
        {onRetry ? (
          <button className="text-button" type="button" onClick={onRetry} disabled={wait > 0}>
            {retryLabel || t.tryAgain}
          </button>
        ) : null}
      </div>
    </div>
  );
}
