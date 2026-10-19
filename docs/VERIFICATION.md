# 실제 검증 기록

대상은 감사 기준 `a83e6d1a73d9ffbcb1b363203de92779779e6082`에 이번 개편을
적용한 소스다. 시작 HEAD는 기준과 같았고 작업 트리는 깨끗했다. 아래 기능 검증은
커밋/푸시·공개 배포 전 수행했으며 Git 이력을 재작성하지 않았다.
이후 원격 반영·배포 여부는 Git 원격 상태와 실제 배포 결과를 별도로 확인해야 한다.
과거 작성자의 기록은 [VERIFICATION_BASELINE.md](VERIFICATION_BASELINE.md)에
보존하며 아래 새 결과와 합산하지 않는다.

Vercel 공개 Host의403과 HTTPS 앱 연결에 대한 후속 수정·실행 결과는
[VERIFICATION_VERCEL_FIX.md](VERIFICATION_VERCEL_FIX.md)에 별도로 기록한다.
이후 사용자의 명시적 비밀번호 제거 요청을 반영한 개인용 기본값과 검증은
[VERIFICATION_PASSWORDLESS.md](VERIFICATION_PASSWORDLESS.md)에 기록한다. 아래의 과거
인증된 개인용 기본값 기록을 현재 비밀번호 요구사항으로 해석하지 않는다.

## 검사 환경

- 호스트: Linux amd64, Python3.12.14, Node24.19.0/npm11.9.0,
  FFmpeg/ffprobe7.1.5, Deno2.9.7.
- 실제 Docker: Engine28.4.0/Compose2.40.3. 이미지 Python3.12.15,
  Debian FFmpeg/ffprobe5.1.9, Deno2.9.7, yt-dlp2026.8.19/EJS0.8.0, Pillow13.0.0.
- 이미지 아키텍처는 linux/amd64만 지원한다. ARM native는 지원하지 않으며 에뮬레이션을
  이 실행에서 검증하지 않았다. TLS·공식 SHA256 검증을 유지했다.
- 최종 runtime 이미지 ID 접두사는 `2a4cbd0049fa`, test는 `336e8184e9e6`이다.
  전체 pytest 원시 로그는 `/tmp/seorap-test-image-bool-results.log`에 있다.
- 전체 브라우저 여정은 동일한 최종 UI/nonce를 담은 `7e338bcbf1b8`에서 실행했다.
  이후 runtime 변경은 잘못된 boolean 환경변수 거부뿐이며, 이 추가3회귀를 포함한
  최신 test 이미지의164개 통과와 최종 runtime source 일치를 별도로 확인했다.
- 개인 데이터와 별개인 `seorap-packaging` 프로젝트/볼륨, 루프백18000에서 합성 검사를
  수행했다. 합성 profile은64MiB 입력/출력·128MiB workspace·2GiB 관리 한도이며
  운영 `.env.example`의5/5/12/50GiB 기본값을 변경하지 않는다.

## 실제 명령과 결과

| 검사 | 명령 | 관측 |
| --- | --- | --- |
| 동결 의존성 | `npm ci` (npm11.9.0) | 성공; Docker/CI도 같은 npm으로 고정 |
| 공개 타입 drift | `.venv/bin/python scripts/export-api-contracts.py --check` | 성공 |
| 타입/린트 | `npm run typecheck`, `npm run lint` | 성공, lint 오류/경고0 |
| 기존 JS/helper | `npm test` | 최종 첫 runner208passed/2skipped, 다음 runner59passed; skip은 로컬 PowerShell 부재 |
| downloader/프록시 회귀 | `npm run test:downloads` |26passed |
| 호스트 전체 백엔드 | `DENO_PATH="$PWD/bin/deno" .venv/bin/python -m pytest backend/tests -rs --tb=short` |155passed/2live-skipped인 통합 시점; 후속 DNS/이름/CSP 회귀는 아래 최신 이미지 검사에 포함 |
| 최종 HTTP 경계 | `.venv/bin/python -m pytest backend/tests/test_http_regressions.py -q` |28passed; malformed URL, 실제 ASGI 바이트, chunked thumbnail, DNS deadline, bootstrap race, Windows reserved names, style nonce, 잘못된 boolean 설정 거부 |
| Docker 전체 회귀 | `docker run --rm --read-only --cap-drop ALL --security-opt no-new-privileges --tmpfs /tmp:rw,size=34359738368,mode=1777 --init seorap:test` |164passed/2live-skipped,63.54초; Starlette/httpx upstream deprecation 경고1, exit0 |
| static SPA | `npm run build:spa` | 성공 |
| Grok/Nitro | `npm run build` | 성공; DATABASE_URL 없는 로컬에서는 migrate skip(의도된 동작) |
| Vercel production 의존성 | `npx --yes --package=npm@11.9.0 npm ci --omit=dev --no-audit --no-fund`, `npm run build` |2026-10-19 후속 게시 준비: 비밀값·데이터 없는 별도 폴더에서310패키지 설치/빌드 성공, devDependencies 없음, lock 동일; output v3/nodejs24.x 생성. 실제 원격 배포 성공과 구분 |
| 초기화·설치 | `node --test scripts/setup-runtime.test.mjs scripts/setup-powershell.test.mjs` |10passed/2PowerShell-skipped |
| preview 소유권·로그 | `python3 -m unittest discover -s scripts -p test_preview_runtime.py -v` |10passed |
| 빌드 QA 종료 | `node --test scripts/preview.test.mjs` |21passed; 실제 미회수 Linux zombie 회귀, 실제 preview:restart→preview:stop exit0·8081 listener 없음 |
| fixture 생성 격리 | `.venv/bin/python -m unittest discover -s scripts -p test_fixture_generator.py -v` |1passed; 사용할 수 없는 외부 DATA_DIR에도 성공, 재실행이 기존 fixture를 변경하지 않음 |
| 임시 백업/복원 | `.venv/bin/python scripts/check-backup.py` |SQLite integrity/설정/합성 operator/파일 SHA256 보존; 사용자 데이터 미접근 |

Docker test tmpfs32GiB는 **가상 상한**이며 실제 fixture는 작은 파일만 사용한다.
1GiB tmpfs로 먼저 실행한 실패는 운영12GiB 예약 정책보다 작은 시험 파일시스템이
원인이었다. 검사 용량을 명시적으로 바로잡았으며 운영 제한이나 assertion을 끄지 않았다.

## 실제 Compose 운영 경계

다음은 설정 파일 검사와 별도로 실제 Docker에서 확인했다.

- 깨끗한 source context에서 runtime/test target 빌드, 공식 Deno checksum/아키텍처 검사.
- UID10001, read-only root, capabilities 전부 제거,256MiB writable runtime tmpfs와 깨끗한
  DENO_DIR에서 도구/엔진 실행. runtime에는 pytest가 없다.
- fresh named volume과 재사용, 준비된0755 bind 디렉터리의 생성·재실행. 관련 네 디렉터리만
  UID10001이 쓰며 관계없는 UID1000 sentinel 파일의 내용/소유권은 유지됐다.
- 탐색 권한 없는0700 import는 명확히 거부하며 권한을 넓히거나 파일을 재귀 chown하지 않는다.
- worker 내부에서 실제 예기치 않은 종료를 일으키면 unless-stopped가 재시작하고 heartbeat가
  회복됐다. 명시적 Compose stop은 중지 상태를 유지했다. Docker kill은 운영자 중지와
  다르게 볼 수 있으므로 예상하지 못한 종료 증거로 대신 세지 않았다.
- 마지막으로 최종 runtime tag를 격리 stack에 적용해 app/worker healthy·initializer exit0,
  CLI-only 초기 설정·인증된 settings/readiness·새 heartbeat·로그아웃 후401을 확인했다.
  컨테이너의 backend Python/SQL28개와 초기화 스크립트가 현재 소스와 SHA256 일치했다.
  이 작업이 만든 불필요한 이미지/빌드 캐시만 정리했고 최종 runtime/test tag와 볼륨은
  유지했다. 실제 `/data` 여유는20,828,868,608bytes(19.40GiB)로 기본12GiB 작업공간
  예약+2GiB 최소 여유 조건을 충족했다. `/tmp/seorap-final-runtime-evidence.json` 참조.
- 관리형 daemon 자체의 재시작은 실행하지 않았다. 실제 Windows bind/PowerShell5.1/7
  실행도 이 Linux 환경에는 없다. 관련 CI 경로는 추가했으며 GitHub CI 실행 결과는 주장하지 않는다.

## 재현 가능한 합성 브라우저 여정

Docker Compose2.24.4 이상의 격리 테스트 profile을 사용한다. 운영 볼륨에 테스트 데이터를
넣지 않는다. 무작위 테스트 비밀번호는 실제 CLI bootstrap으로 설정하고0600 임시 파일에
보관한다. 채팅·로그에 값을 출력하지 않는다.

```sh
python scripts/create-fixtures.py --output /absolute/path/to/empty-fixtures
export SEORAP_FIXTURE_DIR=/absolute/path/to/empty-fixtures
docker compose -p seorap-fixture -f docker-compose.yml -f docker-compose.fixture.yml up -d --build --wait
docker compose -p seorap-fixture -f docker-compose.yml -f docker-compose.fixture.yml exec app python -m app.cli bootstrap
export SEORAP_COMPOSE_PROJECT=seorap-fixture
export SEORAP_COMPOSE_FILES=docker-compose.yml,docker-compose.fixture.yml
export SEORAP_BROWSER_PASSWORD_FILE=/secure/path/to/fixture-password-file
export SEORAP_BROWSER_URL=http://127.0.0.1:18000
npm run test:browser
```

관리형 중첩 Docker 검사에서는 공개 CA secret의 build/runtime mount를 제공하는
`docker-compose.cloud.yml`도 추가했다. 프록시 인증·CA 검증을 우회하지 않았다.
검사 브라우저는 시스템 Chromium과 pinned agent-browser0.39.1 CLI로 실제 동작을
수행하며 Playwright는 동일 CDP 세션의 관측/다운로드/axe 검사에만 쓴다.

최종 전체 여정은2026-10-18T15:04:03Z–15:07:18Z에 exit0/`ok:true`,13게이트를
통과했다. 로그인 실패 복구, 실제 MP4/MP3·native 파일 전송·ffprobe, 오프라인 복구,
active reload/reconnect, 보관/확인 후 삭제/만료, 취소/부모 재시도,35개 합성 기록의
오래된 보관 파일 검색, 설정/키보드/모바일 로그아웃을 포함한다.

실제 분석 결과·긴 제목·실제7개 작업을 함께 둔320/390/768/1280폭과200% CSS zoom,
320/390 설정 대화상자,20개 제한 재생목록·주소 선택/focus를 검사했다. 이 구간에서
실제 설정 변경2회가 성공했으며 소유한 EventSource 최대2개와 새 관측 구간의
network request 객체 최대2개를 각각 확인했다. 이전 페이지에서 늦게 닫히는 request
객체를 실제 열린 연결 수와 혼동하지 않았다.18개 axe 문맥의 위반은0이었다.
stress가 끝난 뒤 합성 작업7개를 취소하고 fixture catalog 원본 바이트/권한을 복구했다.

실제 파일 증거는 MP4 17,522bytes(H.264 320×180/AAC,1초), MP3 44,032bytes
(320kbps,1.07102초)다. native 다운로드도 브라우저가 저장한17,522bytes를 별도로
확인했다. worker가 만든 파일과 다운로드한 파일에 실제 ffprobe를 실행했다.

검사 중 발견한 Radix scroll-lock CSP 오류는 요청별 style nonce와 get-nonce 초기화로
수정했다. 최종 브라우저에서 meta와 inline style nonce 일치·stylesheet 적용·실제 body
scroll-lock을 확인했다. `pageErrors`와 `unexpectedConsoleErrors`는0이다.
일부러 발생시킨 로그인401·만료410·오프라인 ERR_FAILED는 해당 gate/URL까지 기록해
구별하며, 이를 정상 동작의 오류 없는 콘솔이라고 뭉뚱그리지 않는다.

headless Chromium의 Control+Equal 시도는 innerWidth/DPR가 변하지 않았다. 따라서
200% **CSS zoom**과 좁은 폭의 재배치 검사를 통과했다고만 기록하며, native 브라우저
확대의 수동 검사와 NVDA/VoiceOver 실제 실행은 skipped다.

원시 증거: `/workspace/screenshots/downloader-compose-final/verification.json`,
`accessible-tree.json`, 실제 스크린샷과 ffprobe 확인 파일.
판독하기 쉬운320/390 viewport 사진은
`/workspace/screenshots/downloader-queue-detail/actual-result-320-viewport.png`,
`actual-queue-320-viewport.png`, `settings-active-390-viewport.png`에도 있다.

### 별도 Grok 개발/빌드 프로필

8080 개발 UI와8081 최신 빌드 각각에 같은 격리 fixture API/worker를 연결했다.
개인 API는 소유권을 확인해 잠시 중지하고 루프백 릴레이로 합성 stack을 연결했으며
개인 DB를 seed/변경하지 않았다. 각각 **실행한6개 게이트 통과**,5개 axe 문맥 위반0,
실제 로그인·MP4/MP3 처리·native 전송·ffprobe·1280/390 화면을 확인했다.
이 focused 프로필에서 나머지8개 full 여정은 명시적으로 skipped이며13개 전체 검사는
위 Compose 보고서의 결과다. 보고서:

- `/workspace/screenshots/downloader-grok-dev/verification.json`
- `/workspace/screenshots/downloader-grok-built/verification.json`

필수 공통 render smoke도 두 프로필에서 실제 실행했다. 이 환경에는 Playwright 기본
다운로드 바이너리가 없어 설치된 Chromium 경로를 지정했고, 비동기 로그인 화면이
나타날 때까지 selector를 기다렸다. helper의 기본 동작은 유지한다.

```sh
CHROMIUM_PATH=/usr/bin/chromium BROWSER_SMOKE_READY_SELECTOR='#local-password' node scripts/browser-smoke.mjs http://127.0.0.1:8080 /workspace/screenshots/grok-final-dev.png
CHROMIUM_PATH=/usr/bin/chromium BROWSER_SMOKE_READY_SELECTOR='#local-password' node scripts/browser-smoke.mjs http://127.0.0.1:8081 /workspace/screenshots/grok-final-built.png --baseline /workspace/screenshots/grok-final-dev.json
```

두 smoke 모두 desktop/mobile에서 HTTP200, 완전히 표시된 로그인 화면, overflow 없음,
pageErrors0이며 built의 `divergesFromBaseline:false`다. 그러나 각각 **exit2**였다.
원인은 보존한 `https://grok.com/grok-app-builder/extensions.js`의
`net::ERR_TUNNEL_CONNECTION_FAILED`이며, 이 외부 오류를 지우거나 성공으로 바꾸지
않았다. 두 focused 보고서의 `unexpectedConsoleErrors`0은 외부 Grok 오류를
별도 `externalGrok` 배열에 기록한 결과다. 따라서 Grok 외부 통합의 완전한 성공은
현재 네트워크에서 **blocked**다. 자체 앱의 실제 합성 처리 통과와 구분한다.

검사 후 임시 relay와 해당 marker를 제거하고 개인 API/worker/web를 소유권 검증 아래
다시 시작했다. 개인 operator 메타데이터 전체와 작업 수는 검사 전과 일치했고,
API/웹 HTTP200, 배타적 worker heartbeat ready를 확인했다. QA8081은 종료했다.
비밀값 없는 복원 증거는 `/workspace/screenshots/downloader-preview-restoration.json`이다.
QA 종료 도중 발견한 zombie 오판은 `preview.mjs`의 Linux 프로세스 상태 검사로 수정했다.
실제 미회수 zombie는 signal0이 성공해도 종료된 것으로 처리하며, 살아 있는 PID·
알 수 없는 상태·실제 listener의 기존 보수적 검사는 유지한다. 수정 후 실제
`npm run preview:restart`와 `npm run preview:stop`이 모두 exit0이고8081은 닫혔으며
개인 API8000/웹8080은 각각 HTTP200을 유지했다.

클라우드 환경의 설치/시작 초안도 새 소스 경로·인증·소유권 helper·검사 명령에 맞췄다.
npm 버전이 다르면 workspace 안에11.9.0을 설치하도록 했으며 실제 로컬 설치/버전
확인은 통과했다. `grok.com` 허용을 포함한 네트워크 정책은 **저장된 초안**이다.
환경 설정 화면에서 이 초안을 검토하고 게시한 뒤 환경을 다시 시작해 적용해야 한다.
초안 저장을 현재 runtime의 외부 스크립트 차단 해제나 공개 앱 배포로 표현하지 않는다.
새 체크아웃에도 적용하려면 이번 소스 변경이 저장소에 반영되어 있어야 한다.
이 검증 기록을 작성한 시점에는 아직 커밋/푸시 전이었다.

## V01–V22 게이트와 제한

| 게이트 | 구현/검사 처분 |
| --- | --- |
| V01 | clean-folder stub 실패·기존.env 보존·실제 Compose config/image 검사; PowerShell 로컬 skip |
| V02 | 실제 amd64 read-only/nonroot/cache/fresh/reused/prepared bind; ARM native 미지원 |
| V03 | CLI/bootstrap capability/Host·Origin·CSRF/동시 최초 설정·브라우저 로그인·모바일 로그아웃 |
| V04 | SQLite 동시 admission/멱등 충돌/예약·재시작 회귀 |
| V05 | 실제 무응답 입력/FFmpeg 출력 증가, 모든 용량/여유 제한·미게시·정리 |
| V06 | 제어된36초 장기 작업 heartbeat, 실제 OS SIGTERM/descendant/DB fault/worker 재시작 |
| V07 | 합성429·영구 cooldown/backoff·finite403·terminal 정책·metadata slot/deadline |
| V08 | 실제 ASGI open/delete/expire/pin/disconnect·TTL·lease 갱신 |
| V09 | 실제200/206/HEAD/416·Unicode/Windows장치명·symlink/inode/path swap |
| V10 | 논리 오디오 트랙 표현 순열·언어/역할·품질/갱신 불변 |
| V11 | 실제 ffprobe24vs60/rational/VFR/0·90·180·270회전·표시픽셀·duration/codec |
| V12 | exact/approx/unknown/공유입력1회, 저장128/192/320기본값·기존계약불변 |
| V13 | actual ASGI/Node byte limit, malformedURL, HTTP framing/DNS/TLS/redirect/image/deadline |
| V14 | JSON/HTML502/204/429/timeout/abort/offline/401/action 실패의 client 회귀 |
| V15 | revision/order/복원/SSE cap2·polling·bye·late stream 회귀 + 실제 브라우저 |
| V16 | stale analysis generation·정확한 저장 intent/key replay; 기존 영상과 다른 payload 차단 |
| V17 | 실제 fixture API-worker-browser MP4/MP3 + native/API 파일 검사; live와 분리 |
| V18 |35개 synthetic metadata+실제 보관 artifact 검색·paging/settings/storage/locale/theme |
| V19 | 실제 인증320/390/768/1280폭·200% CSS zoom·키보드/18axe/tree; native zoom·OS screen-reader 수동 검사는 미실행 |
| V20 | 기존0001→0002 보존/DDL rollback/metadata·log bounds/임시backup restore |
| V21 | 실제 clean image/npm/type/lint/tests/두 build; CI 정의 추가, 원격 CI 실행 미주장 |
| V22 | **skipped**: 명시적으로 허가된 LIVE_TEST_URL 없음; MP4/MP3 두 검사를 별도로 skip |

FFmpeg 합성 처리, 소유한 로컬 HTTP fixture를 yt-dlp로 내려받은 검사, 렌더링, skipped
live 결과 어느 것도 외부 YouTube 다운로드 성공의 증거가 아니다. 현재 클라우드의
YouTube/CDN 접근도 별도 검증되지 않았다. 공개 egress confinement은 지원 범위 밖이며
썸네일 DNS 방어를 engine 전체의 방화벽이라고 표현하지 않는다.
