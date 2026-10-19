# Vercel 주소와 실제 다운로드 서버 연결

이 저장소의 Vercel 프로젝트는
[foxandwildgoose/youtube-to-mp-4-mp-3](https://vercel.com/foxandwildgoose/youtube-to-mp-4-mp-3)이며
공개 주소는 <https://youtube-to-mp-4-mp-3.vercel.app>이다.
다운로드 서비스는 별도의 지속 실행 서버에서 **SPA와 FastAPI를 함께** 제공한다.
Vercel은 설정된 정식 HTTPS 주소로 사용자를 이동시킨다. 로그인, 분석, SSE, 파일 전송은
이동한 서버의 같은 출처에서 이루어진다. Vercel Function을 통한 API·대용량 파일 중계나
서로 다른 출처 사이의 로그인 쿠키 전달은 사용하지 않는다.

현재 서버 주소가 설정되지 않았다면 Vercel 화면에서 배포 설정이 필요하다는 안내를
표시한다. 화면이 열리거나 Vercel 빌드가 성공한 것만으로 다운로드 서버가 준비된 것은 아니다.

**Windows 노트북에서 개인적으로 쓸 때는 이 외부 서버 절차가 필요 없다.** README의
일반 `scripts/setup.ps1`과 `docker compose`는 비밀번호 없는 로컬 앱을 실행한다.
자동 `docker-compose.override.yml`은 노트북 루프백 주소만 허용하며 기존 `.env`·비밀번호
해시·파일을 유지한다. 아래의 비밀번호 설정은 외부 HTTPS 보호 모드를 직접 선택한 경우에만
해당한다. 아래 모든 `-f` 명령은 개인용 자동 override를 포함하지 않는다.

## 먼저 필요한 운영자 서버

- 운영자가 이미 관리하는 Linux/amd64 호스트와 Docker Compose 2.24.4 이상.
- 해당 호스트를 가리키는 DNS 이름 하나. 아래 `downloads.example.com`은 예시이며 실제 소유한 이름으로 바꾼다.
- 외부에서 서버에 도달하는 TCP 80·443과 DNS A/AAAA 레코드. AAAA가 있다면 IPv6도 실제로 도달해야 한다.
- Caddy의 인증서 발급·갱신과 yt-dlp의 공급자/CDN 접속이 허용된 서버 네트워크.
- SQLite를 둘 로컬 디스크. 기본 정책에서 새 작업을 받으려면 작업공간12GiB와 여유2GiB 이상이 필요하다.

이 절차는 서버·도메인·유료 서비스를 새로 구매하거나 자동으로 준비하지 않는다.
현재 Codex 작업 공간이나 Vercel Function의 임시 파일시스템을 운영 저장소로 쓰지 않는다.
단일 운영자 비밀번호 방식이며 다중 사용자 계정 서비스가 아니다.

## 기존 데이터와 비밀번호를 유지하며 HTTPS 시작

기존 `.env`는 그대로 둔다. 처음 설치하는 호스트에서만 `.env.example`을 `.env`로 복사한다.
운영 중이라면 먼저 README의 일관된 SQLite·미디어 백업 절차를 수행한다.
이전에 별도의 `-p` 프로젝트 이름을 사용했다면 아래 모든 명령에도 같은 `-p`를 추가한다.
프로젝트 이름을 바꾸면 다른 볼륨이 선택되므로 기존 기록이 사라진 것처럼 보일 수 있다.

```sh
export SEORAP_PUBLIC_HOST=downloads.example.com

chmod 0644 deploy/Caddyfile
docker compose -f docker-compose.yml -f docker-compose.https.yml config --quiet
docker compose -f docker-compose.yml -f docker-compose.https.yml build
docker compose -f docker-compose.yml -f docker-compose.https.yml up -d --wait
docker compose -f docker-compose.yml -f docker-compose.https.yml ps
```

`SEORAP_PUBLIC_HOST`에는 `https://`, 포트, 경로, 쉼표나 와일드카드를 넣지 않는다.
Caddyfile은 비밀정보가 없는 공개 설정이며, 권한을 제한한 컨테이너가 읽을 수 있도록0644로 둔다.
이 값을 다음 재시작에도 유지하도록 운영 호스트의 셸/서비스 설정이나 기존 `.env`에
**이 키만** 추가한다. `.env` 전체를 예제 파일로 덮어쓰지 않는다.

HTTPS 오버레이는 API의 기존8000 포트 공개를 제거하고 Caddy만80·443을 공개한다.
API와 작업자의 기존 `seorap-data` 볼륨은 그대로 사용한다. 인증서 저장용 Caddy 볼륨
두 개만 추가한다. `down -v`나 볼륨 삭제 명령을 사용하지 않는다.

오버레이는 `ALLOWED_HOSTS`를 지정한 이름 하나로 제한하고 `LOCAL_HTTP=0`,
`REQUIRE_PASSWORD=1`, `ALLOW_HTTP_BOOTSTRAP=0`을 강제한다. 세션 쿠키는
Secure·HttpOnly로 설정된다. Caddy는 원래 Host/Origin을 유지하며 SSE를 즉시 전달하고,
파일 응답에 별도의 읽기 제한 시간을 추가하지 않는다. 인증과 CSRF 검사는 유지된다.

처음 설치한 데이터 볼륨에서만 비밀번호를 대화식으로 설정한다.

```sh
docker compose -f docker-compose.yml -f docker-compose.https.yml exec app python -m app.cli bootstrap
```

이미 비밀번호가 있다면 재설정하지 않고 기존 비밀번호로 로그인한다. 웹 초기 설정을
허용하거나 `REQUIRE_PASSWORD=0`으로 바꾸지 않는다.

```sh
curl --fail --show-error https://downloads.example.com/healthz
curl --fail --show-error https://downloads.example.com/api/v1/auth/session
docker compose -f docker-compose.yml -f docker-compose.https.yml logs --tail=100 caddy app worker
```

브라우저에서 **실제 서버 주소**에 로그인한 뒤 작업자 준비 상태를 확인한다.
`/healthz` 성공은 API 프로세스 생존만 뜻한다. 로그인·작업자 상태·실제 파일 다운로드를
각각 검증해야 하며, 허가된 YouTube 테스트 URL 없이 실제 공급자 성공을 주장하지 않는다.
인증서 오류가 나면 DNS·80/443 도달성·Caddy 로그를 확인한다. `curl -k`나 TLS 검증 해제로
문제를 숨기지 않는다. 운영 인증서 발급과 실제 YouTube 접속은 별도의 검증 항목이다.

관리형 Codex 환경에서 이미지를 빌드해야 한다면 기존 문서대로
`docker-compose.cloud.yml`을 빌드 명령에 추가하고 제공된 CA 신뢰 설정을 사용한다.
이 파일은 관리형 환경의 프록시/CA를 위한 것이며 일반 Linux 운영 호스트에는 필요 없다.

## 기존 Vercel 프로젝트에 정식 주소 설정

1. 위의 운영 서버에서 HTTPS 로그인과 준비 상태를 먼저 확인한다.
2. [기존 프로젝트](https://vercel.com/foxandwildgoose/youtube-to-mp-4-mp-3)의
   **Settings → Environment Variables**에 서버 전용 `SEORAP_APP_ORIGIN`을 추가한다.
   값은 예를 들어 `https://downloads.example.com`이다. 비밀번호·토큰·경로·쿼리를 넣지 않는다.
3. **Production** 환경에 적용한다. Preview에서도 같은 이동을 원할 때만 Preview에 추가한다.
4. 환경변수 변경 후 **Deployments → 최신 배포 → Redeploy**하거나 `main`의 새 커밋을 배포한다.
5. 공개 Vercel 주소에서 정식 HTTPS 서버로 이동하고, 로그인과 파일 저장이 실제 서버 출처에서
   이루어지는지 확인한다. 기존 도메인을 유지하려면 새로운 Vercel 프로젝트를 만들지 않는다.

`SEORAP_APP_ORIGIN`은 `VITE_` 변수가 아니다. 서버 설정으로만 사용한다.
정식 서버와 같은 Vercel 주소를 넣어 이동 루프를 만들지 않는다.
값이 없거나 올바른 HTTPS origin이 아니면 배포 미설정 상태로 남으며,
개발용 루프백 프록시를 공개 API처럼 사용하지 않는다.

## GitHub 자동 배포 설정

기존 프로젝트 **Settings → Git**에서 `foxandwildgoose/Youtube-to-MP4-MP3`가 연결되어 있는지
확인하고 Production Branch를 `main`으로 둔다. GitHub 연동이 정상이라면 `main` push 후
Vercel이 새 배포를 만들며 `VERCEL_TOKEN`은 필요하지 않다.

| 설정 | 값 |
| --- | --- |
| Root Directory | 저장소 루트 `./` |
| Framework Preset | `Other` |
| Node.js | `24.x` |
| Build Command | `npm run build` |
| Install Command | `vercel.json` 상속 |
| Output Directory | Override 끄기 |

현재 설치 명령은 다음과 같다.

```sh
npx --yes --package=npm@11.9.0 npm ci --omit=dev --no-audit --no-fund
```

Nitro가 `.vercel/output`에 Build Output API 설정·SSR 함수·정적 파일을 생성한다.
`frontend`를 루트로 선택하거나 `build:spa`, `dist`, `.vercel/output/static`으로 설정하지 않는다.
빌드를 통과시키기 위한 가짜 `DATABASE_URL`도 만들지 않는다. 해당 값이 없는 로컬 빌드에서
플랫폼 DB 마이그레이션을 건너뛰는 것은 정상이며 실제 다운로드 DB는 운영 서버의 SQLite이다.

수동 CLI 배포가 필요할 때만 Vercel 인증과 기존 프로젝트 연결을 준비한다.
토큰은 채팅·Git·`.env.example`에 넣지 않고 Codex의 비밀정보 설정으로 제공한다.
Codex에서 배포/공개 주소 검증을 하려면 `api.vercel.com`과 실제 Vercel·운영 호스트에 대한
환경 네트워크 접근도 필요하다. 토큰만 추가해도 네트워크 차단이나 운영 서버 부재가 해결되지는 않는다.

## 검증 범위

다음은 저장소의 추적된 파일만으로 합성 HTTPS 환경과 hosted 브라우저 검사를 재현하는 명령이다.
별도 프로젝트와 테스트 볼륨만 사용한다. `create-fixtures.py`는 기존 출력 폴더가 비어 있지 않으면
거부하므로, 이미 같은 합성 catalog를 만든 경우 생성 명령만 생략한다.

```sh
# 먼저 backend/requirements-test.txt 설치와 Chromium/agent-browser 준비가 필요하다.
export SEORAP_FIXTURE_DIR="$PWD/.cache/https-fixtures"
export SEORAP_PUBLIC_HOST=conversion.example.com
mkdir -p .cache/https-fixture-state
python3 scripts/create-fixtures.py --output "$SEORAP_FIXTURE_DIR"
chmod 0644 deploy/Caddyfile

# 일반 Linux: 아래 목록에서 docker-compose.cloud.yml만 제외한다.
export SEORAP_HTTPS_COMPOSE_FILES=docker-compose.yml,docker-compose.cloud.yml,docker-compose.fixture.yml,docker-compose.https.yml,docker-compose.https-fixture.yml
docker compose -p seorap-https-fixture \
  -f docker-compose.yml -f docker-compose.cloud.yml -f docker-compose.fixture.yml \
  -f docker-compose.https.yml -f docker-compose.https-fixture.yml build
docker compose -p seorap-https-fixture \
  -f docker-compose.yml -f docker-compose.cloud.yml -f docker-compose.fixture.yml \
  -f docker-compose.https.yml -f docker-compose.https-fixture.yml up -d --wait --no-build

export SEORAP_HTTPS_PASSWORD_FILE="$PWD/.cache/https-fixture-state/password"
export SEORAP_HTTPS_CA_FILE="$PWD/.cache/https-fixture-state/root.crt"
export SEORAP_HTTPS_LEAF_FILE="$PWD/.cache/https-fixture-state/leaf.crt"
python3 scripts/bootstrap-fixture.py --project seorap-https-fixture \
  --password-file "$SEORAP_HTTPS_PASSWORD_FILE" --compose-files "$SEORAP_HTTPS_COMPOSE_FILES"
docker cp seorap-https-fixture-caddy-1:/data/caddy/pki/authorities/local/root.crt "$SEORAP_HTTPS_CA_FILE"
python3 - <<'PY'
import os, socket, ssl
from pathlib import Path
context = ssl.create_default_context(cafile=os.environ['SEORAP_HTTPS_CA_FILE'])
with socket.create_connection(('127.0.0.1', 18443), timeout=15) as raw:
    with context.wrap_socket(raw, server_hostname='conversion.example.com') as tls:
        certificate = ssl.DER_cert_to_PEM_cert(tls.getpeercert(binary_form=True))
Path(os.environ['SEORAP_HTTPS_LEAF_FILE']).write_text(certificate)
PY

# 하네스가 기존 개인 프로필의 상태/프로세스 보존도 검사한다.
sh /workspace/startup.sh
curl --fail --silent --show-error http://127.0.0.1:8000/healthz
curl --fail --silent --show-error http://127.0.0.1:8080/ > /dev/null
npm run build
node scripts/test-hosted-deployment.mjs
```

관리형 클라우드는 기존 `docker-compose.cloud.yml`을 더해 제공된 CA와 프록시 설정을 유지한다.
위의 환경에는 실제 운영 `.env` 대신 `.env.example`의 비밀정보 없는 기본값을 전달한다.
내부 CA 인증서는 테스트 프로젝트의 저장소에만 만들고 호스트의 전역 신뢰 저장소에는 설치하지 않는다.
테스트는 명시한 CA와 호스트 이름 검증, Chromium의 정확한 fixture 인증서 공개키와
`conversion.example.com → 127.0.0.1` 매핑을 사용한다. 전체 TLS 검증을 끄지 않는다.
검사 스크립트가 빌드 서버8081을 사용하므로 다른 검사와 동시에 실행하지 않는다.
브라우저 검사 스크립트는 관리형 Codex의 `/etc/codex/network-policy.json`과 Chromium을
사용한다. 일반 Linux에서는 TLS fixture를 실행할 수 있지만 이 관리형 브라우저 하네스의
환경 의존성도 별도로 충족해야 한다.
관리형 환경의 표준 Grok 프로필(API8000·개발 UI8080·개인 작업자)이 건강하게 실행되어 있어야 한다.
하네스는 이 기존 프로필의 DB 메타데이터와 소유한 프로세스 PID/시작 시각을 전후 비교한다.
`/workspace/startup.sh`는 이 저장소의 `startup.sh`를 실행하는 기존 재시작 계약이다.
기존 프로젝트에 이미 비밀번호가 있으면 초기 설정을 반복하지 않고 해당 테스트 비밀번호 파일을 유지한다.

검사가 끝난 뒤 아래 명령은 **이 합성 프로젝트**의 컨테이너와 볼륨만 정리한다.
운영 Compose 이름이나 다른 `-p`로 바꾸어 실행하지 않는다.

```sh
docker compose -p seorap-https-fixture \
  -f docker-compose.yml -f docker-compose.cloud.yml -f docker-compose.fixture.yml \
  -f docker-compose.https.yml -f docker-compose.https-fixture.yml down -v
```

이 구성은 로컬의 격리된 합성 미디어 환경에서 인증서 검증을 유지하는 TLS·로그인·작업자·
파일 전송을 확인할 수 있다. 테스트용 내부 CA 검증은 인터넷 DNS/ACME 인증서 발급이나
실제 YouTube 다운로드 성공과 별개다. 운영 서버 주소가 아직 없다면 공개 다운로드 서비스는
준비되지 않은 상태이며 Vercel의 안내 화면을 실제 다운로드 성공으로 보고하지 않는다.

2026-10-19 로컬 검증에서는 Docker Compose 2.40.3과 위에 고정한 Caddy 2.11.7을
실제로 실행했다. 운영 Caddyfile 검증, 누락된 호스트 거부, API 포트 비공개, 기존 볼륨
이름 유지와 기본 루프백 프로필 보존을 확인했다. 별도 `seorap-https-fixture` 프로젝트에서
내부 CA를 명시적으로 신뢰하고 호스트 이름 검증을 유지한 HTTPS로 다음을 확인했다.

- HTTP308 이동, SPA/CSP 응답, CLI 초기 설정, Secure·HttpOnly 세션과 잘못된 Origin403.
- 준비된 작업자와 도구, 합성 MP4의 H.264/AAC 및 MP3의 실제 파일 다운로드·ffprobe 검사.
- 파일 HEAD200·Range206·비인증401, SSE 첫 snapshot0.053초, 로그아웃 후 세션 거부.

테스트는 루프백18443에서만 실행했으며 개인 데이터 볼륨을 사용하지 않았다.
공개 DNS·ACME 인증서 발급·실제 YouTube 다운로드는 이 결과에 포함되지 않는다.
