/** Server-only routing for a hosted handoff to the complete authenticated app. */
import { isIP } from "node:net";

type DeploymentEnvironment = Record<string, string | undefined>;
export type Deployment =
  { hosted: false; appOrigin: null } | { hosted: true; appOrigin: string | null };

function hostname(value: URL): string {
  return value.hostname.toLowerCase().replace(/\.$/, "");
}
function publicAddress(host: string): boolean {
  const ip = host.replace(/^\[|\]$/g, "");
  if (isIP(ip) === 4) {
    const [a, b, c] = ip.split(".").map(Number);
    return !(
      a === 0 ||
      a === 10 ||
      a === 127 ||
      a >= 224 ||
      (a === 100 && b >= 64 && b <= 127) ||
      (a === 169 && b === 254) ||
      (a === 172 && b >= 16 && b <= 31) ||
      (a === 192 && b === 168) ||
      (a === 192 && b === 0 && (c === 0 || c === 2)) ||
      (a === 192 && b === 88 && c === 99) ||
      (a === 198 && (b === 18 || b === 19)) ||
      (a === 198 && b === 51 && c === 100) ||
      (a === 203 && b === 0 && c === 113)
    );
  }
  if (isIP(ip) === 6) {
    // Only global-unicast IPv6 is eligible. This excludes loopback, mapped IPv4,
    // link-local, unique-local, multicast and translation prefixes.
    const first = Number.parseInt(ip.split(":")[0], 16);
    if (!Number.isFinite(first) || first < 0x2000 || first > 0x3fff) return false;
    const second = Number.parseInt(ip.split(":")[1] || "0", 16);
    if (first === 0x2001 && (second <= 0x1ff || second === 0xdb8)) return false;
    if (first === 0x2002 || /^3fff:/i.test(ip)) return false;
    return true;
  }
  // A dotless or local-use name cannot be the public complete-app origin.
  if (
    !host.includes(".") ||
    /(?:^|\.)(?:localhost|local|internal|invalid|test)$/.test(host) ||
    host.endsWith(".home.arpa")
  )
    return false;
  return host.split(".").every((label) => /^[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?$/.test(label));
}
function frontendHostname(value: string | undefined): string | null {
  if (!value) return null;
  try {
    return hostname(new URL(value.includes("://") ? value : `https://${value}`));
  } catch {
    return null;
  }
}

export function deploymentFor(
  request: Request,
  environment: DeploymentEnvironment = process.env,
): Deployment {
  const hosted =
    ["1", "true"].includes((environment.VERCEL || "").toLowerCase()) ||
    ["production", "preview"].includes((environment.VERCEL_ENV || "").toLowerCase()) ||
    environment.SEORAP_DEPLOYMENT === "hosted" ||
    environment.SEORAP_APP_ORIGIN !== undefined;
  if (!hosted) return { hosted: false, appOrigin: null };
  const target = environment.SEORAP_APP_ORIGIN;
  if (
    !target ||
    target.length > 2048 ||
    Array.from(target).some(
      (character) =>
        character.charCodeAt(0) <= 0x20 || character.charCodeAt(0) === 0x7f || character === "\\",
    ) ||
    !/^https:\/\/[^/?#@]+\/?$/i.test(target)
  )
    return { hosted: true, appOrigin: null };
  try {
    const url = new URL(target);
    const host = hostname(url);
    if (
      url.protocol !== "https:" ||
      url.username ||
      url.password ||
      url.pathname !== "/" ||
      url.search ||
      url.hash ||
      url.port === "0" ||
      !publicAddress(host)
    )
      return { hosted: true, appOrigin: null };
    // Host only comparisons also reject a different-port redirect back to the
    // frontend. Incoming Host is used only to reject loops, never to allow a proxy.
    const frontends = [
      new URL(request.url).hostname,
      request.headers.get("host") || undefined,
      environment.VERCEL_URL,
      environment.VERCEL_PROJECT_PRODUCTION_URL,
    ].map(frontendHostname);
    if (frontends.includes(host)) return { hosted: true, appOrigin: null };
    url.hostname = host;
    return { hosted: true, appOrigin: url.origin };
  } catch {
    return { hosted: true, appOrigin: null };
  }
}

export function ownedBackendPath(path: string): boolean {
  return path === "/healthz" || path === "/api/v1" || path.startsWith("/api/v1/");
}

export function hostedBackendError(configured: boolean): Response {
  return Response.json(
    {
      error: {
        code: configured ? "APP_HANDOFF_REQUIRED" : "DEPLOYMENT_NOT_CONFIGURED",
        message: configured
          ? "다운로드 앱의 시작 화면으로 이동해 주세요."
          : "다운로드 앱의 HTTPS 주소가 설정되지 않았습니다.",
        action: configured
          ? "시작 화면에서 연결된 앱을 여세요. 로그인과 파일 처리는 해당 앱에서 진행됩니다."
          : "운영자가 SEORAP_APP_ORIGIN에 전체 다운로드 앱의 HTTPS 주소를 설정해야 합니다.",
        retryable: false,
      },
    },
    {
      status: 503,
      headers: {
        "Cache-Control": "no-store",
        "Referrer-Policy": "no-referrer",
        "X-Content-Type-Options": "nosniff",
      },
    },
  );
}
