# 서랍 구조와 운영 경계

지원 기본값은 한 사람이 자신의 컴퓨터에서 쓰는 인증된 Docker Compose이다.
React/TypeScript SPA는 같은 출처의 FastAPI가 제공한다. 별도 작업자가 SQLite WAL
큐를 처리하고 yt-dlp/FFmpeg/ffprobe로 검증한 파일만 같은 로컬 볼륨에 게시한다.
프레임워크·인증 스택·큐를 교체하지 않았다. Redis나 외부 유료 변환 API는 사용하지 않는다.

## 실행 상태와 소유권

| 상태 | 다음 상태 | 파일 |
| --- | --- | --- |
| queued | running/cancelled/failed | none |
| running | succeeded/failed/cancelled/interrupted 또는 예약된 queued retry_wait | none |
| succeeded | 실행 종료 | available → expired/deleted/missing |
| failed/cancelled/interrupted | 실행 종료; 명시적 재시도는 자식 작업 | none |

실행 중 취소는 요청일 뿐이다. 소유한 엔진 프로세스 그룹을 TERM→제한된 대기→KILL로
정리하고 회수한 뒤 종료 상태를 저장한다. 콜백/DB 오류·SIGTERM·API 종료도 같은
정리 경로를 쓴다. PID와 시작 시각으로 소유권을 구분하고, 살아 있는 API 분석을
작업자 재시작이 종료하지 않는다. 권위 있는 작업 행이 사라지면 실행을 멈춘다.
활성 기록 삭제를 금지하며 늦은 실패 처리가 이미 보관한 완료 파일을 지우지 않는다.

작업자는 배타적 파일 잠금 하나를 소유한다. 실제 미디어 동시성은1이며 다른 값은
구성 오류이다. 짧은 제어 루프와 미디어 실행을 분리해 긴 작업·진행률이 없는 구간에도
heartbeat, 취소 확인, 제한된 housekeeping이 계속된다. 공급자 cooldown과
next_attempt_at/attempts_used/403 재해석 예산은 SQLite에 저장한다.
이미 시작한 요청은 해당 제한 시간·감시 아래 종료되고, cooldown 중 새 공급자 작업을
시작하지 않는다. 로컬 완료 파일 전송은 공급자 접속과 독립적이다.

## 저장소와 파일

입장 시 BEGIN IMMEDIATE 안에서 멱등성·대기열·분석·부모·예약을 확인한다.
예약 정책은 각 활성/대기 작업에 최대 작업공간 전체(MAX_WORKSPACE_BYTES)를 잡는
보수적 방식이다. 따라서 대기열20은 상한이며, 디스크/50GiB 한도 때문에 실제 입장
수는 더 작을 수 있다. 실제 사용 바이트와 예약 중 아직 쓰지 않은 몫을 구분하고,
claim 직전 재검사한다. SQLite/WAL·로그도 관리 공간 계산에 포함한다.

부모 감시와 다운로드 훅이 입력 총량·출력·작업공간·관리 공간·최소 여유 공간을
실행 중 검사한다. 별도 오디오/영상 입력과 재시도 잔여 파일을 포함한다.
성공은 ffprobe 계약 검사와 원자적 게시 이후에만 가능하다. 종료 때 partial과
예약을 정리하고 보관 파일을 공간 확보를 위해 자동 삭제하지 않는다.

산출물은 서버 ID에서 유도한 files/<job>/output.<ext>만 허용한다.
no-follow 디렉터리/파일 디스크립터와 inode 검사로 state/log/다른 경로를
파일로 내보내지 않는다. 접근 시 상태·TTL·파일 열기·전송 lease를 하나의 트랜잭션으로
확보한다. 전송 중30초마다10분 lease를 갱신하며 완료/연결 중단 시 해제한다.
삭제/만료/보관 변경은 동일한 보호 규칙을 적용한다. Linux에서는 이미 열린 파일이
unlink 뒤에도 읽힐 수 있으므로 이를 임의 전송 중단으로 가정하지 않는다.

## 미디어 계약

선택은 재정렬과 무관한 논리 트랙(language/role/provider track identity)을 저장하고
codec/bitrate/protocol 표현과 분리한다. 허용 표현 중 품질 기준에 따라 결정적으로
선택하며 새 메타데이터에서 언어·품질 의도가 사라지면 FORMAT_CHANGED를 반환한다.
임시 signed URL은 자식 프로세스 안에만 남는다. just-resolved 형식으로 내려받아
동일 URL의 불필요한 재추출을 피하며 모든 분석에 별도 deadline/slot을 적용한다.

호환 MP4는 실제 H.264·8bit420 SDR 및 존재하는 오디오의 AAC이다. 가능한 입력은
복사/리먹스하며 영상 변환은 명시적 서버 허용+사용자 동의가 필요하다. MP3의 오디오
인코딩은 이 영상 변환 스위치와 별개다. 업스케일·프레임 보간·HDR 톤 매핑은 하지 않는다.
인코딩 크기·표시 크기·회전을 구분하고30/60/rational FPS·duration·stream 수·codec을
검증한다. 입력/출력 추정/작업공간 예산은 서로 다른 값이며 approximate/unknown을
확정값으로 바꾸지 않는다. 공유 muxed 입력은 한 번만 센다.

## 개발 UI와 보안

Grok 프로필은8080 개발 서버,8081 빌드 확인과 루프백 처리 서비스가 함께 있어야 한다.
Grok PWA injector, 브랜딩, PreviewHostBridge와 사전 연결된 플랫폼 소스는 보존한다.
들어온 실제 Host/Origin/본문을 검사한 뒤에만 개발 프록시가 trusted loopback 헤더를
쓴다. `.env`의 운영 인증을 preview가 몰래 끄지 않는다. frontend-only Vercel 출력은
영구 작업자/미디어 저장소를 제공하지 않으며 API 없는 상태는 오류로 표시한다.

scrypt 비밀번호, 해시된 HttpOnly 세션, CSRF, 동일 출처 Host/Origin을 유지한다.
잘못된 boolean 환경변수는 구성 오류로 거부해 오타가 인증 해제로 해석되지 않는다.
운영 SPA HTML마다 style nonce를 발급하고 응답 CSP·meta·Radix의 get-nonce에 같은
값을 연결한다. 대화상자 scroll-lock 스타일은 허용하되 script CSP를 완화하지 않는다.
nonce가 든 HTML은 no-store다.
기본 공개 포트는127.0.0.1이다. LAN/VPN/공개 서비스는 별도 검증한 인증·TLS·egress
계약 없이는 지원하지 않는다. canonical YouTube URL과 썸네일 DNS 고정은 yt-dlp의
모든 CDN/리다이렉트를 방화벽으로 가두는 것과 다르다. 이 변경은 공개 서비스의
SSRF 차단을 주장하지 않으며 쿠키 수입·DRM/멤버 우회·CAPTCHA 우회·임의 옵션을
추가하지 않는다. 로컬 데이터 디렉터리 변조 검사는 조건부 파일 경계 강화이다.

썸네일은 TLS 호스트 검증·공개 DNS 주소 고정·리다이렉트 재검사·443포트·총 deadline·
바이트 상한을 유지한다. 표준 HTTPResponse가 chunked framing을 해독하고 Pillow가
이미지를 검증한다. DNS 조회도 제한 시간과 최대2개 작업의 상한을 갖는다.
최대32개/16MB/5분 캐시이며 실패는 캐시하지 않는다.

## 수명·마이그레이션

0002는 예약과 재시도 상태/인덱스를 추가하는 비파괴 마이그레이션이다.
DDL과 버전 마커가 함께 커밋되며 실패하면 rollback한다. 참조된 분석·부모·보관 파일은
유지하고 만료된 미참조 분석/세션/lease/slot/cooldown/로그인 시도와 보통 기록을
작은 배치로 정리한다. 삭제한 키는7일 tombstone 후 재사용 가능하다.
FFmpeg 진단은 bounded tail, progress는 점진 읽기, preview 로그는 크기별2개 백업,
Compose 로그는 자체 json-file 회전을 쓴다. 업데이트 전 DB와 미디어를 함께 백업한다.
