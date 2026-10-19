# 서랍 · YouTube MP4 / MP3

YouTube 영상 주소 하나로 MP4 영상 또는 MP3 오디오를 만들고 자신의 컴퓨터에
보관하는 한국어 우선 개인 도구입니다. 영어와 밝게/어둡게/시스템 테마를 지원합니다.
React·FastAPI·별도 작업자·SQLite·yt-dlp·FFmpeg 구조를 유지했습니다.

받을 권리가 있는 자료만 저장하세요. 저작권과 YouTube 약관은 별개이며 개인적 사용이
자동으로 허락을 뜻하지 않습니다. 자신의 업로드는
[YouTube Studio/Takeout 안내](https://support.google.com/youtube/answer/56100?hl=ko)를
참고하세요. [YouTube 약관](https://www.youtube.com/static?template=terms).

## 지원 기본 실행: 비밀번호 없는 개인용 로컬 Docker Compose

Docker Engine/Desktop와 Compose **2.24.4 이상**, Linux amd64 이미지를 사용합니다.
ARM 머신은 명시적 amd64 에뮬레이션이 필요하며 네이티브 ARM 이미지는 지원하지 않습니다.
앱과 작업자는 UID10001, 읽기 전용 루트, 전용 영구 볼륨을 사용하고
`127.0.0.1:8000`에만 공개합니다. 노트북에서 사용하는 기본 구성은 로그인이나
비밀번호 설정 없이 바로 열립니다. 별도 소유 호스트의 단일 운영자 HTTPS 구성은
[Vercel과 변환 서버 연결](docs/VERCEL_DEPLOYMENT.md)을 따릅니다.

Linux/macOS:

```sh
sh scripts/setup.sh
```

Windows PowerShell5.1 또는7:

```powershell
powershell -ExecutionPolicy Bypass -File .\scripts\setup.ps1
```

설치 스크립트는 없는 `.env`만 비밀값 없는 `.env.example`에서 만들며 기존 파일을
덮어쓰지 않습니다. Docker CLI·Compose·daemon과 시작 준비를 따로 확인합니다.
설치가 끝나면 **http://127.0.0.1:8000** 을 열어 바로 사용하세요. 비밀번호 설정 명령은
필요하지 않습니다. `docker-compose.override.yml`이 개인용 설정을 자동 적용하므로
기존 `.env`에 `REQUIRE_PASSWORD=1`이 남아 있어도 파일을 수정하지 않고 로그인 없이
열립니다. 이미 저장된 비밀번호 해시·작업 기록·파일은 삭제하지 않습니다.

```sh
docker compose up -d --wait
docker compose stop
docker compose start
docker compose logs --tail 100 app worker
```

`unless-stopped`는 예상하지 못한 종료를 복구하고 명시적 중지는 존중합니다.
healthcheck는 재시작 정책 자체가 아니며, 긴 미디어 작업 중에도 heartbeat가 유지됩니다.
볼륨 삭제(`down -v`)는 비밀번호·기록·파일을 없애므로 업데이트에 사용하지 않습니다.

이전에 실행한 컨테이너에는 최신 코드를 받은 뒤 `docker compose up -d --build --wait`로
개인용 설정을 적용합니다. `docker compose start`는 기존 컨테이너를 켜기만 하므로
설정 변경을 반영하지 않습니다. 이 모드는 같은 노트북에서만 사용합니다. 외부 공개
HTTPS 프로필은 [별도 명령](docs/VERCEL_DEPLOYMENT.md)으로 선택하며 비밀번호 보호를
유지합니다. 그 문서의 CLI 비밀번호 설정은 외부 HTTPS 보호 모드에만 해당합니다.

비밀번호 없는 첫 접속·새로고침·세션 만료 복구와 실제 테스트 파일 전송의 실행 결과는
[개인용 비밀번호 제거 검증](docs/VERIFICATION_PASSWORDLESS.md)에 기록했습니다.

새 named volume은 필요한 네 디렉터리만 초기화합니다. 기존 볼륨 전체를 재귀 chown하지
않습니다. 호스트 bind mount를 사용하려면 해당 **전용** 디렉터리와 `state/tmp/files/logs`를
UID/GID10001에 미리 허용하고 초기화기가 탐색할 수 있도록 전용 루트는0755로 준비하세요. SQLite를 SMB/NFS에 두지 마세요. Docker Desktop의
Windows bind-mount 권한은 플랫폼별로 확인해야 하며 named volume이 기본입니다.
다른 UID로 만든 기존 데이터를 가져오면 먼저 서비스 중지·백업 후 SQLite DB/WAL/SHM과
`files/<job-id>`·`tmp/<job-id>`의 디렉터리/파일에도 UID10001이 필요한 읽기·쓰기·탐색
권한을 갖도록 관리자가 해당 경로만 준비해야 합니다. 초기화기는 기존 파일 소유권을
자동 변환하지 않으며, 관련 없는 파일이나 호스트 전체의 권한을 바꾸지 마세요.

## 사용 흐름

1. MP4 영상 또는 MP3 오디오를 고르고 주소를 붙여 넣어 **링크 분석**합니다.
2. 실제 서버 선택지의 권장 출력·화질·오디오 언어를 확인하고 **MP4/MP3 만들기**를 누릅니다.
3. 서버가 처리하고 검증을 마친 뒤 **이 기기에 받기**로 기존 파일을 전송합니다.

주소를 바꾸면 이전 분석/동의를 무효화합니다. 응답이 유실된 만들기 요청은 같은 제출
키로 복구하며, 의도한 새 작업과 구별합니다. 활성 작업은 새로고침과 SSE 실패 후에도
반복 조회로 복구합니다. 기록 검색·형식/상태/파일 필터·페이지 이동으로 오래된 보관 파일도
찾을 수 있습니다. ‘서버 파일 삭제’와 ‘기록 삭제’는 별개이며 파일 삭제에는 확인이 필요합니다.
브라우저 다운로드 폴더/다른 이름으로 저장 설정이 기기 목적지를 정합니다. 클릭만으로
기기 저장이 끝났다고 보고하지 않습니다.

호환 MP4는 H.264·8bit420 SDR/AAC입니다. 적합한 스트림은 복사/리먹스합니다.
영상 변환은 서버 스위치와 명시적 동의가 필요합니다. MP3는128/192/320kbps 인코딩이며
기본192kbps(설정에서 변경)입니다. 높은 출력 비트레이트가 잃어버린 원본 품질을 복원하지
않습니다. 원본 오디오는 고급 옵션이며 업로더의 마스터 파일이 아닙니다.

설정의 언어·테마·MP3 기본값은 다음 작업에 적용하며 이미 큐에 들어간 계약은 바꾸지
않습니다. source title/channel은 번역하지 않습니다. 선택적 재생목록 검사는 기본 끔,
최대20개 위치만 확인하고 사용자가 고른 한 영상만 분석합니다. 로그인/멤버/DRM/진행 중
라이브 우회, 자막/채널 일괄 수집, 프록시 회전은 제공하지 않습니다.

## 기본 정책과 저장소

| 항목 | 기본값 |
| --- | --- |
| 미디어/분석 동시성 | 각각1 (미디어는1만 지원) |
| 대기 작업 상한 |20|
| 분석 유효시간/제한시간 |10분/60초|
| 영상 길이/작업 활성 제한시간 |4시간/2시간(큐 대기 제외)|
| 네이티브 MP4 상한/권장 선택 |실제 제공될 때2160p/1080p 이하|
| 명시적 SDR 영상 변환 |기본 끔,1080p 이하|
| 입력/최종 파일/작업공간 |각5GiB/5GiB/12GiB|
| 전체 관리공간/최소 디스크 여유 |50GiB/2GiB|
| 보관하지 않은 완료 파일/일반 기록 |24시간/90일|
| 추가 자동 시도 |최대2회, 영구 cooldown/backoff 적용|

예약은 입장한 작업마다 작업공간 최대값을 잡는 보수적 정책이므로 실제 입장 수는
디스크와 용량에 따라20보다 작습니다. 입력 크기·추정 출력·작업공간은 다른 개념입니다.
실행 중 실제 바이트를 검사하며 보관 파일은 공간 확보를 위해 자동 삭제하지 않습니다.
DB/WAL와 로그도 전체 관리공간에 포함합니다. 파일은 `/data/files`, DB는 `/data/state`입니다.

## 개발과 회귀 검사

Node22.12 이상 또는24, **npm11.9.0**, Python3.12, FFmpeg/ffprobe 및 Deno2.9.7을
사용합니다. Docker 이미지와 CI도 npm 버전을 맞춥니다. Deno 설치는 공식 amd64
SHA256을 검증하며 mismatch에서 실패합니다. 실행 중 자동 업데이트하지 않습니다.

```sh
npm ci
python3 -m venv .venv
.venv/bin/python -m pip install -r backend/requirements-test.txt
sh scripts/install-deno.sh "$PWD/bin"
export PATH="$PWD/bin:$PWD/.venv/bin:$PATH"
npm run check:contracts
npm run typecheck
npm run lint
npm test
npm run test:downloads
python -m pytest backend/tests -rs
python scripts/check-backup.py
npm run build:spa
```

테스트 도구는 명시적 `FFMPEG_PATH/FFPROBE_PATH/DENO_PATH` 다음 PATH 순서로 찾습니다.
기본 회귀는 실제 합성 미디어를 사용하며 YouTube에 접속하지 않습니다. 런타임 이미지에는
pytest를 넣지 않으며 `--target test`가 별도의 테스트 환경입니다.

```sh
docker build --target test -t seorap:test .
docker run --rm --read-only --cap-drop ALL --security-opt no-new-privileges --tmpfs /tmp:rw,size=34359738368,mode=1777 --init seorap:test
```

합성 Compose/브라우저 여정은 [검증 기록](docs/VERIFICATION.md)의 명령을 사용합니다.
격리된 테스트 볼륨과 테스트 비밀번호 파일을 요구하며 일반 데이터에 seed/만료 조작을
하지 못하도록 보호합니다. 실제 YouTube 검사는 명시적 허가를 받은 짧은
`LIVE_TEST_URL`이 있을 때만 MP4/MP3 두 검사를 수행합니다. 없으면 skipped이며
합성 파일·화면 렌더링을 라이브 성공으로 간주하지 않습니다.

Grok 개발 프로필은 별도입니다:

```sh
sh /workspace/startup.sh
npm run build
npm run preview:restart
npm run preview:stop
```

8080 개발 UI, 루프백8000 API, 별도 작업자를 함께 실행합니다. `startup.sh`는 독립적으로
부족한 프로세스만 복구합니다. 개인용 비밀번호 없는 모드와 명시적 보호 모드를 구분하며
PWA 브랜딩·미리보기 브리지는
유지합니다. `npm run build`의 frontend-only Nitro/Vercel 출력만으로 영구 처리 서비스가
생기지는 않습니다. API 없이 보이는 화면은 동작하는 다운로더의 증거가 아닙니다.
알려진 플랫폼 프록시를 추가해야 한다면 `SEORAP_PREVIEW_ALLOWED_HOSTS`에 실제
요청 Host(포트 포함), `SEORAP_PREVIEW_ORIGINS`에 정확한 Origin을 쉼표로 구분해
설정하고 개발/빌드 서버를 재시작하세요. 와일드카드나 임의 출처는 허용하지 않습니다.
관리형 클라우드에서 중첩 Docker의 프록시 CA가 필요하면
`docker-compose.cloud.yml`을 추가하고 `CODEX_PROXY_CERT` 바인딩을 사용합니다.
TLS/서명/체크섬 검증을 끄지 않습니다.

Vercel의 `Ready`는 웹 빌드 배포 상태입니다. FastAPI·작업자·SQLite·미디어 파일이
그 배포만으로 생성되지는 않습니다. Vercel에서 서버 주소가 없으면 서비스 연결이
필요하다는 상태를 표시합니다. 전체 앱을 제공하는 HTTPS 호스트가 준비되면 Vercel의
서버 환경변수 `SEORAP_APP_ORIGIN`에 해당 origin을 설정하고 재배포하세요.
Vercel 진입 주소에서 전체 앱으로 이동하며 로그인·SSE·대용량 파일 전송은 동일한
변환 서버 주소에서 처리합니다. 자세한 명령과 전제는 위 배포 문서에 있습니다.

## 업데이트·백업·복원

마이그레이션0002는 기존 비밀번호·기록·보관 파일을 유지하며 예약/재시도 상태와 인덱스를
추가합니다. 실패하면 DDL과 버전 마커를 함께 rollback합니다. 먼저 앱/작업자를 중지하고
SQLite backup API로 일관된 DB 복사본을 만든 뒤 media files와 함께 외부에 백업하세요.
실행 중인 DB 본체만 복사하고 WAL을 무시하지 마세요.

```sh
docker compose stop app worker
docker compose run --rm --no-deps --entrypoint python app -c "import sqlite3; s=sqlite3.connect('/data/state/app.db'); t=sqlite3.connect('/data/state/app.db.bak'); s.backup(t); t.close(); s.close()"
docker compose start app worker
```

체크아웃에서 SQLite 백업은 `DATA_DIR=/path/to/volume python scripts/backup.py /path/to/app.db.bak`.
`state` 백업과 `files`를 함께 보존하고, 복원은 두 서비스를 중지한 상태에서 수행합니다.
보존한 DB로 교체할 때 이전 `-wal/-shm`도 함께 정리하고 동일 시점 파일을 복원합니다.
시험 복원은 별도 볼륨에서 하세요. 이전 이미지 태그와 일치하는 DB/파일 백업을 보관해야
롤백할 수 있으며 schema downgrade를 자동 실행하지 않습니다. yt-dlp/EJS는 함께
고정·재빌드·fixture 재검증하고 이전 이미지 태그를 유지하세요.

## 문서와 라이선스

- [구조·보안·저장소 경계](docs/ARCHITECTURE.md)
- [API와 오류 계약](docs/API.md)
- [전체60개 이슈 추적](docs/ISSUE_TRACEABILITY.md)
- [실제 실행 명령·검증 결과·제한](docs/VERIFICATION.md)
- [초기 의사결정/상태 표](docs/OVERHAUL_DECISIONS.md)

각 구성요소의 라이선스는 별개입니다: yt-dlp(Unlicense), Deno/React/FastAPI/Starlette/
Uvicorn/Pydantic(MIT), Pillow(HPND), yt-dlp-ejs(배포 패키지 메타데이터 참고),
FFmpeg(이미지의 Debian 빌드 구성과 저작권 파일 참고). cobalt/MeTube 등의 코드는
복사하지 않았습니다. 비교 서비스의 처리 속도·안전·4K 성공을 보장하지 않습니다.
