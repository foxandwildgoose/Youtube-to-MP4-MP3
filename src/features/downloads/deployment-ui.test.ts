import assert from "node:assert/strict";
import { test } from "node:test";
import { localizedError, offlinePresentation, translate, type Locale } from "./i18n.ts";

for (const locale of ["ko", "en"] as const satisfies readonly Locale[]) {
  test(`unconfigured conversion service shows connection guidance and manual retry in ${locale}`, () => {
    const copy = offlinePresentation(locale, "DEPLOYMENT_NOT_CONFIGURED");
    assert.equal(copy.action, "retry");
    assert.equal(copy.actionLabel, translate(locale).checkAgain);
    assert.notEqual(copy.title, translate(locale).offlineTitle);
    assert.notEqual(
      localizedError("DEPLOYMENT_NOT_CONFIGURED", locale),
      localizedError("CSRF_FAILED", locale),
    );
    assert.notEqual(
      localizedError("DEPLOYMENT_NOT_CONFIGURED", locale),
      translate(locale).requestFailed,
    );
  });

  test(`connected app handoff offers reopening instead of repeating session requests in ${locale}`, () => {
    const copy = offlinePresentation(locale, "APP_HANDOFF_REQUIRED");
    assert.equal(copy.action, "open_app");
    assert.equal(copy.actionLabel, translate(locale).openApp);
    assert.notEqual(copy.title, offlinePresentation(locale, "DEPLOYMENT_NOT_CONFIGURED").title);
    assert.notEqual(
      localizedError("APP_HANDOFF_REQUIRED", locale),
      localizedError("CSRF_FAILED", locale),
    );
    assert.notEqual(
      localizedError("APP_HANDOFF_REQUIRED", locale),
      translate(locale).requestFailed,
    );
  });

  test(`ordinary outage retains existing recovery in ${locale}`, () => {
    const copy = offlinePresentation(locale, "NETWORK_ERROR");
    assert.equal(copy.action, "retry");
    assert.equal(copy.title, translate(locale).offlineTitle);
    assert.equal(copy.body, translate(locale).offlineBody);
  });
}
