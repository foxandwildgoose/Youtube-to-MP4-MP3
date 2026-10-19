import type { Settings } from "./contracts.ts";
export type Preferences = Pick<Settings, "language" | "theme" | "mp3_bitrate">;
export const defaultPreferences: Preferences = {
  language: "ko",
  theme: "system",
  mp3_bitrate: 192,
};
export function localPreferences(storage?: Pick<Storage, "getItem">): Preferences {
  try {
    const language = storage?.getItem("seorap-lang");
    const theme = storage?.getItem("seorap-theme");
    const bitrate = Number(storage?.getItem("seorap-mp3-bitrate"));
    return {
      language: language === "en" ? "en" : "ko",
      theme: theme === "light" || theme === "dark" ? theme : "system",
      mp3_bitrate: bitrate === 128 || bitrate === 192 || bitrate === 320 ? bitrate : 192,
    };
  } catch {
    return defaultPreferences;
  }
}
export function persistPreferences(value: Preferences, storage?: Pick<Storage, "setItem">): void {
  try {
    storage?.setItem("seorap-lang", value.language);
    storage?.setItem("seorap-theme", value.theme);
    storage?.setItem("seorap-mp3-bitrate", String(value.mp3_bitrate));
  } catch {
    /* Private browsing/storage denial must not break preferences. */
  }
}
/** Serialize full snapshots so an older save can never commit after a newer save. */
export class PreferenceWriter {
  private tail: Promise<unknown> = Promise.resolve();
  private generation = 0;
  save<T>(write: () => Promise<T>, accept: (value: T) => void): Promise<T> {
    const generation = ++this.generation;
    const result = this.tail.catch(() => undefined).then(write);
    this.tail = result;
    return result.then((value) => {
      if (generation === this.generation) accept(value);
      return value;
    });
  }
  invalidate(): void {
    this.generation += 1;
  }
}
