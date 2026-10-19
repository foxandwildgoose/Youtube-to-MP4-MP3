import { useMemo, useState } from "react";
import * as Dialog from "@radix-ui/react-dialog";
import { CircleHelp, Copy, Settings2, X } from "lucide-react";
import type { Settings } from "../api";
import { translate, type Locale } from "../i18n";
import { BusyLabel, ErrorNotice, type DisplayError } from "./presentation";
import { formatBytes } from "./formatters";

type Preferences = Partial<Pick<Settings, "language" | "theme" | "mp3_bitrate">>;
export function SettingsDialog({
  locale,
  theme,
  settings,
  ready,
  busy,
  error,
  diagnosticsError,
  diagnosticsValue,
  onSave,
  onDiagnostics,
  diagnosticsBusy,
  processingReady,
}: {
  locale: Locale;
  theme: "light" | "dark" | "system";
  settings: Settings | null;
  ready: boolean;
  busy: boolean;
  error?: DisplayError | null;
  diagnosticsError?: DisplayError | null;
  diagnosticsValue: Record<string, unknown> | null;
  onSave: (values: Preferences) => void;
  onDiagnostics: () => void;
  diagnosticsBusy: boolean;
  processingReady: boolean | null;
}) {
  const t = translate(locale);
  const [copied, setCopied] = useState<"yes" | "failed" | null>(null);
  const safeDetails = useMemo(() => {
    if (!diagnosticsValue) return "";
    const permitted = [
      "ready",
      "database",
      "storage_writable",
      "free_bytes",
      "managed_bytes",
      "minimum_free_bytes",
      "storage_limit_bytes",
      "versions",
    ];
    return JSON.stringify(
      Object.fromEntries(
        permitted
          .filter((key) => key in diagnosticsValue)
          .map((key) => [key, diagnosticsValue[key]]),
      ),
      null,
      2,
    );
  }, [diagnosticsValue]);
  async function copyDetails() {
    try {
      await navigator.clipboard.writeText(safeDetails);
      setCopied("yes");
    } catch {
      setCopied("failed");
    }
  }
  const cap = settings?.capabilities;
  return (
    <Dialog.Root>
      <Dialog.Trigger asChild>
        <button type="button" className="button secondary compact" aria-label={t.settings}>
          <Settings2 className="icon" aria-hidden="true" />
          <span>{t.settings}</span>
        </button>
      </Dialog.Trigger>
      <Dialog.Portal>
        <Dialog.Overlay className="dialog-overlay" />
        <Dialog.Content
          className="dialog-content settings-dialog"
          aria-describedby="settings-description"
        >
          <div className="section-heading">
            <Dialog.Title className="dialog-title">{t.settings}</Dialog.Title>
            <Dialog.Close asChild>
              <button type="button" className="icon-button" aria-label={t.close}>
                <X className="icon" />
              </button>
            </Dialog.Close>
          </div>
          <Dialog.Description id="settings-description" className="muted small">
            {t.settingsDescription}
          </Dialog.Description>
          <div className="settings-fields" aria-busy={busy}>
            <label className="field">
              <span>{t.language}</span>
              <select
                value={locale}
                onChange={(event) => onSave({ language: event.target.value as Locale })}
              >
                <option value="ko">한국어</option>
                <option value="en">English</option>
              </select>
            </label>
            <label className="field">
              <span>{t.theme}</span>
              <select
                value={theme}
                onChange={(event) => onSave({ theme: event.target.value as Settings["theme"] })}
              >
                <option value="system">{t.themeSystem}</option>
                <option value="light">{t.themeLight}</option>
                <option value="dark">{t.themeDark}</option>
              </select>
            </label>
            <label className="field">
              <span>{t.mp3Preference}</span>
              <select
                value={settings?.mp3_bitrate || 192}
                disabled={!ready}
                aria-describedby="bitrate-preference-hint"
                onChange={(event) =>
                  onSave({ mp3_bitrate: Number(event.target.value) as Settings["mp3_bitrate"] })
                }
              >
                {[128, 192, 320].map((n) => (
                  <option key={n} value={n}>
                    {n} kbps
                  </option>
                ))}
              </select>
              <span className="small muted" id="bitrate-preference-hint">
                {t.preferenceHint}
              </span>
            </label>
          </div>
          <p className="small muted" role="status">
            <BusyLabel busy={busy}>{busy ? t.saving : t.preferencesSaved}</BusyLabel>
          </p>
          <ErrorNotice error={error} locale={locale} />
          {cap ? (
            <div className="settings-information">
              <h3>{t.capabilities}</h3>
              <dl className="fact-list small">
                <div>
                  <dt>{t.quota}</dt>
                  <dd className="numeric">
                    {formatBytes(cap.storage_used_bytes)} / {formatBytes(cap.storage_limit_bytes)}
                  </dd>
                </div>
                <div>
                  <dt>{t.filePolicy}</dt>
                  <dd>
                    {cap.file_ttl_seconds >= 86400
                      ? `${Math.round((cap.file_ttl_seconds / 86400) * 10) / 10} ${t.days}`
                      : `${Math.round((cap.file_ttl_seconds / 3600) * 10) / 10} ${t.hours}`}
                  </dd>
                </div>
                <div>
                  <dt>{t.nativeCap}</dt>
                  <dd>{cap.native_cap}p</dd>
                </div>
                <div>
                  <dt>{t.defaultCap}</dt>
                  <dd>{cap.default_cap}p</dd>
                </div>
                <div>
                  <dt>{t.convert}</dt>
                  <dd>{cap.transcoding_enabled ? t.enabled : t.disabled}</dd>
                </div>
                <div>
                  <dt>{t.playlistTitle}</dt>
                  <dd>{cap.playlists_enabled ? t.enabled : t.disabled}</dd>
                </div>
                <div>
                  <dt>{t.processor}</dt>
                  <dd>
                    {processingReady == null
                      ? t.unknown
                      : processingReady
                        ? t.processorReady
                        : t.offline}
                  </dd>
                </div>
              </dl>
              <p className="small muted">
                {t.capHint} {t.keepHint}
              </p>
            </div>
          ) : null}
          {ready ? (
            <details className="help-details">
              <summary>
                <CircleHelp className="icon" aria-hidden="true" />
                {t.diagnostics}
              </summary>
              <p className="small muted">{t.diagnosticHint}</p>
              <button
                className="button secondary"
                type="button"
                disabled={diagnosticsBusy}
                onClick={onDiagnostics}
              >
                <BusyLabel busy={diagnosticsBusy}>{t.diagnosticRun}</BusyLabel>
              </button>
              <ErrorNotice error={diagnosticsError} locale={locale} />
              {diagnosticsValue ? (
                <>
                  <p className="small">
                    {t.processor}:{" "}
                    {diagnosticsValue.ready ? t.processorReady : t.processorUnavailable}
                  </p>
                  <details className="technical-details">
                    <summary>{t.details}</summary>
                    <pre className="safe-diagnostics" tabIndex={0}>
                      {safeDetails}
                    </pre>
                    <button
                      type="button"
                      className="button secondary"
                      onClick={() => void copyDetails()}
                    >
                      <Copy className="icon" aria-hidden="true" />
                      {t.copyDetails}
                    </button>
                    <p role="status" className="small muted">
                      {copied === "yes" ? t.copied : copied === "failed" ? t.copyFailed : ""}
                    </p>
                  </details>
                </>
              ) : null}
            </details>
          ) : null}
        </Dialog.Content>
      </Dialog.Portal>
    </Dialog.Root>
  );
}
