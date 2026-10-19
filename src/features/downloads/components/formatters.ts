import type { Choice, Job } from "../api";
import { translate, type Locale } from "../i18n";

export function formatDuration(seconds: number | null | undefined): string {
  if (seconds == null || !Number.isFinite(seconds) || seconds < 0) return "—";
  const total = Math.round(seconds);
  const h = Math.floor(total / 3600),
    m = Math.floor((total % 3600) / 60),
    s = total % 60;
  return h
    ? `${h}:${String(m).padStart(2, "0")}:${String(s).padStart(2, "0")}`
    : `${m}:${String(s).padStart(2, "0")}`;
}
export function formatBytes(value: number | null | undefined): string {
  if (value == null || !Number.isFinite(value) || value < 0) return "—";
  const units = ["B", "KiB", "MiB", "GiB", "TiB"];
  let n = value,
    i = 0;
  while (n >= 1024 && i < units.length - 1) {
    n /= 1024;
    i++;
  }
  return `${n.toFixed(n >= 10 || i === 0 ? 0 : 1)} ${units[i]}`;
}
export function formatDate(value: string | null | undefined, locale: Locale): string {
  if (!value || !Number.isFinite(new Date(value).getTime())) return "—";
  return new Intl.DateTimeFormat(locale === "ko" ? "ko-KR" : "en-GB", {
    dateStyle: "medium",
    timeStyle: "short",
  }).format(new Date(value));
}
type OutputFacts = Partial<Choice> & {
  kind: string;
  container: string;
  conversion_required: boolean;
};
export function outputSummary(output: OutputFacts | Job["output"], locale: Locale): string {
  const t = translate(locale),
    facts = output as OutputFacts;
  const kind = facts.kind === "original_audio" ? t.tabOriginal : facts.kind.toUpperCase();
  const resolution =
    facts.resolution_label ||
    (facts.width && facts.height ? `${facts.width}×${facts.height}` : null);
  const fps =
    facts.fps != null && Number.isFinite(facts.fps)
      ? `${Math.round(facts.fps * 100) / 100} fps`
      : null;
  const bitrate = facts.bitrate_kbps ? `${facts.bitrate_kbps} kbps` : null;
  return [
    kind,
    facts.kind === "mp4" ? resolution : bitrate,
    facts.kind === "mp4" ? fps : null,
    facts.audio_language,
    facts.audio_role && facts.audio_role in t.role
      ? t.role[facts.audio_role as keyof typeof t.role]
      : null,
    facts.kind === "original_audio" ? facts.container.toUpperCase() : null,
  ]
    .filter(Boolean)
    .join(" · ");
}
export function choiceLabel(choice: Choice, locale: Locale): string {
  const t = translate(locale);
  return [
    outputSummary(choice, locale),
    choice.kind === "mp4" && choice.conversion_required ? t.convert : null,
    choice.is_default ? t.recommended : null,
  ]
    .filter(Boolean)
    .join(" · ");
}
