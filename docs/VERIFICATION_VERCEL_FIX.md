# Vercel 403 및 변환 서비스 연결 수정 검증

대상은 GitHub `4792fffaef1139ed9fd9b419946cf463b3a40ca2` 이후 수정이다.
운영 프로젝트는 `foxandwildgoose/youtube-to-mp-4-mp-3`, 진입 주소는
<https://youtube-to-mp-4-mp-3.vercel.app>이다. 사용자 화면에서 이전 버전의
`CSRF_FAILED · HTTP403`을 확인했고, 같은 공개 Host로 기존 middleware 경로도 재현했다.

## 원인과 실제 수정

이전 Nitro 배포에도 로컬 Grok bridge가 실행되어 공개 Host를 루프백 전용 정책으로
거부했다. 공개 Host만 허용해도 Vercel 내부에 원래 가정한 API8000/worker/SQLite/파일
볼륨이 없으므로 실제 변환은 되지 않는다. 비밀번호·CSRF 보호를 해제하지 않았다.

Hosted 경로는 로컬 프록시를 실행하지 않는다. `SEORAP_APP_ORIGIN`이 없거나 잘못되면
API는503 `DEPLOYMENT_NOT_CONFIGURED`, 화면은 서비스 연결 필요 상태를 표시한다.
올바른 전체 앱 HTTPS origin이 있으면 시작 문서만307/no-store로 이동한다.
기존에 열려 있던 화면은503 `APP_HANDOFF_REQUIRED`에 따라 기본 링크로 시작 문서를
다시 연다. API·SSE·파일을 Vercel을 통해 중계하거나 로그인 쿠키를 다른 출처에 전달하지 않는다.

실제 앱은 동일한 HTTPS 출처에서 SPA·FastAPI·작업자·로컬 SQLite/파일을 제공한다.
새 HTTPS Compose overlay는 기존 데이터 볼륨을 유지하며 Caddy만80/443을 공개한다.
서버·DNS를 자동 구매하거나 현재 작업 공간을 운영 서버로 공개하지 않는다.
운영 전제와 정확한 명령은 [VERCEL_DEPLOYMENT.md](VERCEL_DEPLOYMENT.md)에 있다.

## 실행한 자동 검사

| 검사 | 실제 결과 |
| --- | --- |
| `npm run test:downloads` |45passed: 기존26 + 실제 middleware13 + UI 상태/현지화6 |
| `npm test` |209passed/2PowerShell-skipped, 다음 runner59passed |
| `npm run typecheck`, `npm run lint`, `npm run check:contracts` |모두 성공 |
| `npm run build`, `npm run build:spa` |모두 성공; 플랫폼 DATABASE_URL 미설정 migration skip은 정상 |
| `npm run check:vercel` |생성된 Vercel function의 default.fetch를 직접 호출해8checks 통과; 외부 요청0 |
| HTTPS Compose config 검사 |API/worker 외부 포트 없음, Caddy80/443만 공개, 정확한 Host·보호된 인증·보안 쿠키·CLI 초기 설정 강제 |
| `node scripts/test-hosted-deployment.mjs` |실제 브라우저7gates 통과, axe9contexts/0violations, 예기치 않은 console 오류0/pageErrors0 |

실제 middleware 회귀는 잘못된/사설/예약 주소·동일 호스트 이동 루프·사용자 정보 포함URL,
PWA 설치·플랫폼 auth 경로 보존, hosted 원격 요청0, 로컬 Range/SSE/취소/본문 제한 및
원래 Host/Origin 거부를 검사한다. 생성 function 검사는 Vite wrapper를 우회하므로
Nitro에 포함된 middleware 순서와 실제 공개 Host 요청의503/307도 따로 확인한다.
두 검사를 GitHub CI에 추가했지만 원격 CI 성공을 실행했다고 주장하지 않는다.
빌드 preview의 준비 확인도 실제307을 성공으로 판정하며 정식 앱으로 이동하지 않도록
수정했다. 실제 HTTP 서버 회귀22개에 이동 목적지를 요청하지 않는 검사도 포함된다.

## 실제 HTTPS 변환 서버 fixture

원래 개인 데이터 및 기존 fixture와 별도인 `seorap-https-fixture` 프로젝트를 사용했다.
테스트 주소 `conversion.example.com:18443`은 소유한 로컬 테스트 서버에만 매핑했으며
공개 DNS나 운영 ACME 인증서 발급을 수행하지 않았다. 공식 Caddy2.11.7의 검증된
manifest digest를 고정했다. 생성 인증서와 로컬 CA로 TLS 체인·호스트 검증을 유지했다.

- HTTP308, 전체 SPA200/CSP, CLI-only 초기 설정 확인.
- 다른 Origin의 로그인403, 올바른 HTTPS 로그인 및 Secure/HttpOnly 세션 확인.
- 실제 worker heartbeat와 필수 도구 준비 상태 확인.
- 실제 MP4 17,522bytes(H.264/AAC), MP3 26,474bytes 생성 후 TLS 전송·ffprobe 확인.
- 파일 HEAD200/Range206, 인증 없는 전송401, 로그아웃 후 세션 무효화 확인.
- SSE 첫 snapshot 약0.053초: 응답 버퍼링 때문에 진행 표시가 지연되지 않음 확인.

원시 증거: `/tmp/seorap-https-fixture-evidence.json`.
합성 파일의 성공은 YouTube 다운로드 성공이 아니다. 허가된 live URL이 없어 실제
YouTube 검사는 실행하지 않았다.

## 실제 브라우저와 운영 제한

최종 브라우저 실행 `e2c94c0e`는7gates를 모두 통과했다. 미설정 한국어/영어 상태를
데스크톱·모바일에서 확인했고 수동 재시도1회와 자동 재시도0회를 관측했다. 같은 문서를
유지한 채 설정된 QA 서버로 바꾸고 `APP_HANDOFF_REQUIRED` → 기본 링크 → 실제307 →
HTTPS 로그인 화면을 확인했다. Secure·HttpOnly·SameSite=Lax 세션, 잘못된 Origin403,
미인증 작업401, Vercel 출처에 세션 쿠키가 남지 않는 것도 확인했다.

각각 UI에서 요청한 형식과 새 작업의 실제 형식이 같은지, 기본 다운로드 링크의 경로가
그 새 작업의 `/api/v1/jobs/<id>/file`인지 검사했다. 네이티브 브라우저 전송 완료 후
MP4 17,522bytes(H.264/AAC), MP3 26,478bytes(192kbps)를 실제 파일의 ffprobe로 확인했다.
이전에 만든 다른 fixture 파일을 새 작업의 성공으로 계산하지 않는다.
9개 화면의 axe 자동 검사 위반0건, 예기치 않은 console 오류0건, pageErrors0건이었다.
개인 API/개발 UI/작업자의 PID·생성 시각·소유권과 기존 운영자 메타데이터·작업 수가
동일했고 마지막에도 API/웹 정상 응답과 작업자 heartbeat를 확인했다. 소유한 QA8081은
검사 후 닫았다. 원시 보고서는 `/workspace/screenshots/hosted-deployment-final/verification.json`이다.

초기 하네스 실행은 준비 확인의307 추적, 소비 후 취소된 CDP 응답 본문 조회, 로컬
fixture의 브라우저 프록시 처리 때문에 중단되어 최종 성공 증거로 사용하지 않았다.
하네스를 수정하고 형식·작업 파일 식별 검사를 강화한 버전을 다시 실행했다.
보존된 시도와 초기 로그 재사용의 한계는 같은 폴더의 `harness-repair-history.json`에 있다.
테스트의 설치된 Chromium은 해당 로컬 fixture의 인증서 공개키만 고정해 사용하며
해당 이름만127.0.0.1로 매핑한다. 다른 외부 요청의 프록시와 TLS 정책은 유지한다.
일반 운영 TLS 검증이나 외부 네트워크 정책을 해제하지 않는다. 새 브라우저 하네스는
이 관리형 환경에서 실행했으며 CI에는 생성 function·Compose 경계 검사만 추가했다.

필수 `scripts/browser-smoke.mjs`도 개인 개발 UI와 기본 빌드 preview 양쪽에서 실행했다.
데스크톱·모바일 모두HTTP200/실제 초기 설정 내용/가로 넘침 없음/pageErrors0이었고,
네 스크린샷을 직접 확인했다. 빌드와 개발 화면의 divergence는false였다. 두 실행 모두
외부 `grok.com/grok-app-builder/extensions.js`의 터널 차단 console 오류 때문에exit2였다.
따라서 전체 smoke가 성공했다고 표시하지 않는다. 브랜딩 스크립트는 유지했다.
원시 결과는 `/workspace/screenshots/vercel-fix-dev.json`, `vercel-fix-built.json`이다.

검사 뒤 새 `seorap-https-fixture`의 소유권을 확인한4컨테이너·네트워크·3테스트 볼륨만
정리했다. 기존 `seorap-packaging` 컨테이너 ID와 개인 API/개발 UI 정상 상태는 유지했다.
정리 후 디스크 여유18.01GiB로 기본 작업공간12GiB+여유2GiB 조건도 회복했다.
증거와 공개 테스트 인증서는 보존했으며 운영 데이터나 비밀번호는 삭제하지 않았다.

현재 클라우드에서 운영 주소 직접 요청은 HTTPS CONNECT403으로 차단되어 운영
사이트의 응답을 직접 읽지 못했다. 필요한 도메인은 환경 초안에 추가했으나 초안
저장이 현재 런타임 정책 적용을 뜻하지 않는다. Vercel CLI도 로그인 정보가 없다.
실제 운영 앱 호스트와 DNS/HTTPS 주소가 아직 제공되지 않아 공개 다운로드의 완전한
준비를 주장할 수 없다. GitHub 반영과 자동 배포 요청, 원격 배포 완료 확인은 구분한다.
