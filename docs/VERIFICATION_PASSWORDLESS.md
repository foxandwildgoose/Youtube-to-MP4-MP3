# 개인용 비밀번호 제거 및 실제 검증

사용자의 최신 요청은 개인 Windows 노트북에서 비밀번호를 설정하거나 로그인하지 않고
앱을 여는 것이다. 이전 `e8a19dd`의 인증된 개인용 기본값을 이 요청에 맞춰 변경했다.
과거 감사 문서의 비밀번호 요구사항을 현재 사용자 선호보다 우선하지 않는다.

## 적용한 변경

- 일반 `docker compose`가 자동으로 읽는 `docker-compose.override.yml`에서 개인용
  앱과 작업자에 `REQUIRE_PASSWORD=0`을 적용한다. 공개 포트는127.0.0.1:8000,
  허용 Host는127.0.0.1/localhost이며 웹 비밀번호 초기 설정도 필요 없다.
- 기존 `.env`에 `REQUIRE_PASSWORD=1`이 있어도 파일 원문을 덮어쓰지 않고 적용된다.
  저장된 비밀번호 해시·설정·작업·파일을 삭제하거나 DB를 초기화하지 않는다.
- Windows/Linux 설치 출력과 README의 필수 비밀번호 설정 단계를 제거했다.
  개발 preview 기본값도0이며, 소유한 API와 작업자를 재시작해 현재 실행에 적용했다.
- 내부 HttpOnly/SameSite 세션은 자동 발급한다. Host/Origin/CSRF 검사는 유지한다.
  첫 접속·새로고침·새 브라우저에서는 로그인/초기 비밀번호/로그아웃 UI가 없다.
- 만료·쿠키 소실에 따른401 또는 CSRF 거부는 하나의 세션 갱신을 공유한다. 거부된
  원래 작업만 동일 본문·멱등성 키로 한 번 재시도한다. 네트워크 오류·시간 초과·5xx는
  자동 재실행하지 않으며 반복 실패는 연결 오류로 표시한다.
- 명시적 HTTPS 보호 프로필과 보호 모드 회귀 fixture는 별도이며 비밀번호 보호를
  유지한다. Vercel의 운영 앱 주소 설정·실제 변환 서버 문제를 비밀번호 제거와 혼동하지 않는다.

기존 Windows 설치에서는 최신 소스를 받은 동일 폴더에서 다음 명령으로 반영한다.
프로젝트 이름과 기존 데이터 볼륨을 유지한다.

```powershell
docker compose up -d --build --wait
```

새 설치에서는 다음 명령만 실행하고 앱 주소를 연다. CLI bootstrap 단계가 없다.

```powershell
powershell -ExecutionPolicy Bypass -File .\scripts\setup.ps1
```

## 실행한 검사

| 검사 | 실제 결과 |
| --- | --- |
| `npm run test:downloads` |59passed: 기존45 + 세션 갱신·취소·같은 제출 보존14 |
| `python -m pytest backend/tests/test_passwordless_access.py -q` |23passed; 독립 임시 SQLite/합성 미디어 사용 |
| `python -m pytest backend/tests -q` |189개 중187passed/허가된 live URL 없는2skipped |
| `npm test` |첫 runner211passed/PowerShell2skipped; 다음 runner59passed |
| setup 전용 Node 회귀 |12passed/PowerShell2skipped; 실제 Compose 설정 검사 포함 |
| `python3 -m unittest discover -s scripts -p test_preview_runtime.py -v` |12passed |
| 타입·ESLint·공개 API 계약 |성공 |
| `npm run build`, `npm run build:spa` |두 빌드 성공 |
| `npm run check:vercel` |생성된 실제 Vercel function8checks 성공 |
| 실제 Linux/amd64 runtime 이미지 빌드 |성공; CA/TLS 검증 유지 |
| `node scripts/test-passwordless-browser.mjs` |최종361b8958:7/7gates, axe6contexts 위반0 |

백엔드 회귀는 비밀번호/운영자 행 없는 접속, 재접속, 세션 만료·폐기·쿠키 소실,
기존 운영자 행과 비밀번호 해시·설정·작업 보존, 보호 모드 복귀, Host/Origin/CSRF,
실제 합성 MP4/MP3 완료 및 파일 전송을 검사했다. 프런트 회귀는 동시 갱신,
늦게 도착한401, 호출자 취소·로그아웃·보호 모드 전환, 중복 작업 방지를 검사했다.

## 실제 브라우저 증거

완전히 별도인 `seorap-passwordless-fixture`의 새 이미지/볼륨과 루프백18002를 사용했다.
개인 `.env` 대신 `.env.example`만 컨테이너에 전달하고 테스트용 합성 어댑터임을 확인했다.
운영 비밀번호·개인 DB를 읽거나 변경하지 않았다.

최종 실행은 첫 접속, 저장한320kbps 설정과 새로고침, 쿠키 소실, 실제 DB 세션 만료,
모바일, 쿠키가 비어 있는 새 브라우저를 확인했다. bootstrap/login/logout 요청은0회였다.
두 복구 경로에서 각각 **실제 작업 요청401 한 번 → 세션200 한 번 →
같은 요청202 한 번**을 관측했으며 새 작업은 정확히 하나였다.

실제 브라우저의 파일 저장 완료 후 새 작업의 정확한 파일 경로·바이트 수·ffprobe를 확인했다.

- MP4: `04a4ba57929dd9c3ce54ee791a22f432`,17,522bytes,H.264/AAC.
- MP3: `c0d1bdeeec9ca0731daca6cd6065ed69`,44,032bytes,320kbps MP3.

예상하지 않은 console 오류·페이지 오류·전송 실패는0이었다. 초기 실행의 정상 취소
분류 누락과 자동 입력의 URL 중복은 하네스에서 진단·수정하고 전체를 재실행했다.
취소 분류는 소유한 정확한 읽기 경로의 ERR_ABORTED와 현재 성공 응답, 또는 실제 파일
전송 완료 증거가 있는 경우만 허용한다. 변경 요청의 실패는 숨기지 않는다.
보존된 초기 실패 보고서·화면과 최종 결과는 `/workspace/screenshots/passwordless-final/`에 있다.
최종 stdout은 `/workspace/screenshots/passwordless-final-run3.log`이다.

개인 개발 UI와 기본 빌드 preview에도 필수 `scripts/browser-smoke.mjs`를 실행했다.
데스크톱·모바일 모두 실제 작업 화면/HTTP200/가로 넘침 없음/pageErrors0,
빌드와 개발 divergence=false였고 네 스크린샷을 직접 확인했다. 두 smoke는 외부
Grok 스크립트의 기존 터널 차단 때문에exit2였다. 전체 smoke 성공으로 표시하지 않는다.
Grok 통합은 유지했다.

검사 후 소유권을 확인한 새 테스트 컨테이너·네트워크·볼륨만 정리했다. 기존 보호
fixture의 컨테이너 ID·시작 정보·마운트와 개인 서비스 PID·생성 시각·운영자/작업
메타데이터는 유지했다. 이 빌드에서 생성된13개의 공유되지 않은 BuildKit cache ID만
추가 정리해 디스크 여유15.178GiB를 회복했다. 검증한 runtime 이미지와 증거 파일은
보존했다. 개인 앱의 비밀번호 없는 접속과 처리/작업자/필수 도구 준비 상태를 다시
확인했으며 기존 운영자 행·작업 수는 변경되지 않았다.

## 재현과 확인하지 않은 범위

브라우저 fixture의 기본 명령은 아래와 같다. 관리형 클라우드에서는 기존 지침대로
`docker-compose.cloud.yml`을 base 다음에 추가하고 제공된 CA와 프록시를 유지한다.
일반 CI에서는 cloud overlay를 사용하지 않는다.

```sh
export SEORAP_FIXTURE_DIR="$PWD/.cache/passwordless-fixtures"
python scripts/create-fixtures.py --output "$SEORAP_FIXTURE_DIR"
docker compose -p seorap-passwordless-fixture -f docker-compose.yml -f docker-compose.fixture.yml -f docker-compose.override.yml -f docker-compose.passwordless-fixture.yml build volume-init
docker compose -p seorap-passwordless-fixture -f docker-compose.yml -f docker-compose.fixture.yml -f docker-compose.override.yml -f docker-compose.passwordless-fixture.yml up -d --no-build --wait
node scripts/test-passwordless-browser.mjs
```

스크립트는 Chromium·agent-browser·ffprobe와 빌드된 이미지가 필요하다. 기존 fixture
폴더가 비어 있지 않으면 생성기를 반복 실행하지 않는다. 스크린샷 경로 등 하네스의
작업 디렉터리는 CI 설정을 따른다. GitHub CI에 동일 fixture 여정을 추가했지만 원격 CI
성공을 관측한 것은 아니다. Windows 네이티브 PowerShell 실행은 현재 Linux 환경에서
실행하지 못했으며 Windows CI matrix를 유지했다.

합성 미디어 성공은 YouTube 성공이 아니다. 허가된 live URL이 없어 실제 YouTube
검사는 실행하지 않았다. Vercel 원격 Ready 확인은 기존 네트워크·인증 제한으로
수행하지 못했으며, 현재 사용자 노트북에 변경을 원격 설치했다고 주장하지 않는다.
