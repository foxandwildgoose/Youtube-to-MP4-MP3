import { useState } from "react";
import * as AlertDialog from "@radix-ui/react-alert-dialog";
import { Check, Download, FileAudio, FileVideo, Trash2 } from "lucide-react";
import type { Job } from "../api";
import { translate, type Locale } from "../i18n";
import { BusyLabel, ErrorNotice, type DisplayError } from "./presentation";
import { formatBytes, formatDate, formatDuration, outputSummary } from "./formatters";

export type JobAction = "cancel" | "retain" | "deleteFile" | "deleteHistory";
export function JobCard({
  job,
  locale,
  error,
  pending,
  onAction,
  onRetry,
  onDownload,
}: {
  job: Job;
  locale: Locale;
  error?: DisplayError | null;
  pending: Record<string, boolean>;
  onAction: (action: JobAction, id: string, keep?: boolean) => void;
  onRetry: (job: Job) => void;
  onDownload: (job: Job) => void;
}) {
  const t = translate(locale),
    active = job.status === "queued" || job.status === "running";
  const [confirmOpen, setConfirmOpen] = useState(false);
  const isPending = (action: string) => Boolean(pending[`${job.id}:${action}`]);
  const locked = Object.entries(pending).some(
    ([key, value]) => key.startsWith(`${job.id}:`) && value,
  );
  const retryScheduled =
    active && Boolean(job.next_attempt_at && Date.parse(job.next_attempt_at) > Date.now());
  const phase = retryScheduled
    ? t.phase.waiting
    : job.phase && job.phase in t.phase
      ? t.phase[job.phase as keyof typeof t.phase]
      : t.status[job.status];
  const p = job.progress;
  const component = (p as Job["progress"] & { component?: string })?.component;
  const meaningfulDownload =
    active && job.phase === "downloading" && (!p?.phase || p.phase === job.phase);
  const total = p?.total_bytes;
  const downloaded = p?.downloaded_bytes;
  const known =
    meaningfulDownload &&
    typeof total === "number" &&
    Number.isFinite(total) &&
    total > 0 &&
    !p?.total_is_estimate &&
    typeof downloaded === "number" &&
    Number.isFinite(downloaded) &&
    downloaded >= 0;
  const percent = known ? Math.min(100, Math.max(0, (downloaded! / total!) * 100)) : null;
  const speed =
    meaningfulDownload && p?.speed_bps != null && Number.isFinite(p.speed_bps) && p.speed_bps > 0
      ? p.speed_bps
      : null;
  const eta =
    active &&
    p?.eta_seconds != null &&
    Number.isFinite(p.eta_seconds) &&
    p.eta_seconds >= 0 &&
    (!p.phase || p.phase === job.phase) &&
    ["downloading", "transcoding", "encoding"].includes(job.phase || "")
      ? p.eta_seconds
      : null;
  const isAudio = job.output.kind !== "mp4";
  return (
    <article className="job-card" data-job-id={job.id} aria-labelledby={`job-${job.id}-title`}>
      <div className="job-heading">
        <span className="file-icon" aria-hidden="true">
          {isAudio ? <FileAudio /> : <FileVideo />}
        </span>
        <div className="job-heading-copy">
          <h3 id={`job-${job.id}-title`}>{job.source.title || job.source.video_id || t.unknown}</h3>
          <p className="output-label">{outputSummary(job.output, locale)}</p>
          <p className="small muted">{job.source.channel || ""}</p>
        </div>
        <span className={`status-chip ${job.file_state === "available" ? "status-ready" : ""}`}>
          {job.file_state === "available" ? <Check className="icon" aria-hidden="true" /> : null}
          {active ? phase : t.status[job.status]}
        </span>
      </div>
      {active ? (
        <div className="job-progress">
          <div className="progress-copy">
            <span>
              {phase}
              {job.queue_position != null ? ` · ${t.queue} ${job.queue_position}` : ""}
              {component ? ` · ${component in t ? t[component as "video"] : t.component}` : ""}
            </span>
            <span className="numeric">{percent == null ? "" : `${Math.floor(percent)}%`}</span>
          </div>
          <div
            className="progress-track"
            role="progressbar"
            aria-label={`${outputSummary(job.output, locale)} · ${phase}`}
            aria-valuemin={0}
            aria-valuemax={100}
            aria-valuenow={percent == null ? undefined : Math.round(percent)}
            aria-valuetext={
              percent == null
                ? `${phase} · ${t.unknownProgress}`
                : `${phase} ${Math.round(percent)}%`
            }
          >
            <div
              className={percent == null ? "indeterminate progress-fill" : "progress-fill"}
              style={percent == null ? undefined : { width: `${percent}%` }}
            />
          </div>
          <div className="progress-facts small muted numeric">
            {meaningfulDownload ? (
              <span>
                {formatBytes(downloaded)} /{" "}
                {total == null
                  ? t.unknown
                  : `${p?.total_is_estimate ? `${t.estimate} ` : ""}${formatBytes(total)}`}
              </span>
            ) : (
              <span>{phase}</span>
            )}
            <span>
              {t.speed}: {speed == null ? "—" : `${formatBytes(speed)}/s`}
            </span>
            <span>
              {t.eta}: {eta == null ? "—" : formatDuration(eta)}
            </span>
          </div>
          {retryScheduled ? (
            <p className="small muted numeric">
              {t.phase.waiting} · {formatDate(job.next_attempt_at, locale)}
            </p>
          ) : null}
          {job.cancel_requested ? (
            <p className="small" role="status">
              {t.cancelling}
            </p>
          ) : null}
        </div>
      ) : null}
      {job.error ? (
        <ErrorNotice
          error={{
            ...job.error,
            retryAt: job.next_attempt_at
              ? Date.parse(job.next_attempt_at)
              : job.error.retry_after_seconds
                ? Date.parse(job.updated_at) + job.error.retry_after_seconds * 1000
                : null,
          }}
          locale={locale}
        />
      ) : null}
      <div className="artifact-facts small">
        <span className={job.file_state === "available" ? "file-available" : "muted"}>
          {t.fileState[job.file_state]}
        </span>
        {job.artifact ? (
          <>
            <span className="numeric">{formatBytes(job.artifact.bytes)}</span>
            <span>
              {job.keep_on_server
                ? t.stored
                : job.artifact.expires_at
                  ? `${t.expiry} ${formatDate(job.artifact.expires_at, locale)}`
                  : t.neverExpires}
            </span>
          </>
        ) : null}
      </div>
      {job.artifact?.filename ? (
        <p className="filename small">
          <span className="muted">{t.filename}: </span>
          {job.artifact.filename}
        </p>
      ) : null}
      <div className="job-actions">
        {job.file_state === "available" ? (
          <button
            type="button"
            className="button primary"
            onClick={() => onDownload(job)}
            disabled={locked}
          >
            <BusyLabel busy={isPending("download")}>
              <Download className="icon inline-icon" aria-hidden="true" />
              {isPending("download") ? t.downloading : t.download}
            </BusyLabel>
          </button>
        ) : null}
        {active ? (
          <button
            className="button secondary"
            type="button"
            disabled={locked || job.cancel_requested}
            onClick={() => onAction("cancel", job.id)}
          >
            <BusyLabel busy={isPending("cancel")}>{t.cancel}</BusyLabel>
          </button>
        ) : null}
        {job.file_state === "available" ? (
          <button
            className="button secondary"
            type="button"
            disabled={locked}
            onClick={() => onAction("retain", job.id, !job.keep_on_server)}
          >
            <BusyLabel busy={isPending("retain")}>
              {job.keep_on_server ? t.expire : t.keep}
            </BusyLabel>
          </button>
        ) : null}
        {!active ? (
          <button
            className="button secondary"
            type="button"
            disabled={locked}
            onClick={() => onRetry(job)}
          >
            {job.status === "succeeded" ? t.redownload : t.retry}
          </button>
        ) : null}
        {job.file_state === "available" ? (
          <AlertDialog.Root open={confirmOpen} onOpenChange={setConfirmOpen}>
            <AlertDialog.Trigger asChild>
              <button type="button" className="button danger-quiet" disabled={locked}>
                <Trash2 className="icon" aria-hidden="true" />
                {t.deleteFile}
              </button>
            </AlertDialog.Trigger>
            <AlertDialog.Portal>
              <AlertDialog.Overlay className="dialog-overlay" />
              <AlertDialog.Content className="dialog-content confirm-dialog">
                <AlertDialog.Title className="dialog-title">{t.deleteTitle}</AlertDialog.Title>
                <AlertDialog.Description className="muted">
                  {t.deleteDescription}
                </AlertDialog.Description>
                <p className="filename small">
                  {job.artifact?.filename || outputSummary(job.output, locale)}
                </p>
                <div className="dialog-actions">
                  <AlertDialog.Cancel asChild>
                    <button type="button" className="button secondary">
                      {t.back}
                    </button>
                  </AlertDialog.Cancel>
                  <AlertDialog.Action asChild>
                    <button
                      type="button"
                      className="button danger"
                      onClick={() => onAction("deleteFile", job.id)}
                    >
                      {t.deleteConfirm}
                    </button>
                  </AlertDialog.Action>
                </div>
              </AlertDialog.Content>
            </AlertDialog.Portal>
          </AlertDialog.Root>
        ) : !active ? (
          <button
            type="button"
            className="button text-button"
            disabled={locked}
            onClick={() => onAction("deleteHistory", job.id)}
          >
            <BusyLabel busy={isPending("deleteHistory")}>{t.deleteHistory}</BusyLabel>
          </button>
        ) : null}
      </div>
      {error ? <ErrorNotice error={error} locale={locale} /> : null}
      <details className="technical-details">
        <summary>{t.details}</summary>
        <dl className="fact-list small">
          <div>
            <dt>{t.createdAt}</dt>
            <dd>{formatDate(job.created_at, locale)}</dd>
          </div>
          <div>
            <dt>{t.updatedAt}</dt>
            <dd>{formatDate(job.updated_at, locale)}</dd>
          </div>
          <div>
            <dt>{t.sourceIdentity}</dt>
            <dd>{job.source.video_id || "—"}</dd>
          </div>
          <div>
            <dt>{t.confirmLabel}</dt>
            <dd>
              {job.output.kind === "mp3"
                ? t.audioEncoding
                : job.output.conversion_required
                  ? t.convert
                  : t.copy}
            </dd>
          </div>
        </dl>
        {job.source.canonical_url ? (
          <a
            href={job.source.canonical_url}
            target="_blank"
            rel="noreferrer"
            className="text-link small"
          >
            {t.source}
          </a>
        ) : null}
      </details>
    </article>
  );
}
