# API와 상태 계약

FastAPI의 `/api/v1/openapi.json`은 요청과 공개 응답 모델을 제공한다.
`backend/app/public_models.py` → `scripts/export-api-contracts.py` →
`src/features/downloads/public-contracts.generated.ts`가 응답 필드의 기준이다.
클라이언트는 생성된 타입을 보강하고 중요한 응답을 실행 중에도 검사한다.
`python scripts/export-api-contracts.py --check`로 생성 파일 불일치를 검사한다.

- `GET /healthz`: 프로세스 생존만 확인한다. YouTube 연결이나 작업자 준비를 뜻하지 않는다.
- `GET /api/v1/auth/session`: 인증, 비밀번호 설정 여부, `bootstrap_allowed`,
  `bootstrap_method`를 반환한다. Compose 기본은 CLI 설정이며, 금지된 웹 설정을 제시하지 않는다.
- `POST /auth/bootstrap`, `/auth/login`, `/auth/logout`: Host/Origin·요청 표시 헤더를
  검사한다. 로그인/변경 요청에는 같은 출처, 인증 후 변경에는 CSRF 토큰도 필요하다.
  비밀번호는 평문 저장하지 않는다. 초기 웹 설정은 명시적 허용+루프백에서만 가능하며
  초기 설정의 존재 검사와 저장은 같은 트랜잭션으로 수행한다.
- `POST /analyses`: 제한 시간과 전역 분석 슬롯·공급자 cooldown을 적용한다.
  분석 ID, 만료, 소스, 논리 오디오 트랙, 서버 선택지 및 유효 MP3 기본값을 반환한다.
  signed CDN URL과 임의 엔진 옵션은 공개하지 않는다.
- `POST /jobs`: `Idempotency-Key`와 정확한 분석/선택 ID를 필요로 한다.
  결과를 잃으면 같은 본문과 키로 재전송한다. 다른 본문으로 같은 키를 쓰면409이다.
  삭제된 작업 키는 삭제 후7일 tombstone으로 남으며 그 동안 새 작업으로 재사용되지 않는다.
- `GET /jobs?active=true`: 현재 작업을 기록 페이지와 독립적으로 찾는다.
  `active=false&limit=20&offset=0&search=...&format=mp3&status=...&file_state=available`
  는 기록의 검색·필터·페이징을 제공한다. `total`, `limit`, `offset`을 반환한다.
- `GET /jobs/{id}`, `/jobs/{id}/events`: revision이 증가하는 스냅샷이다.
  SSE `bye`는 인증 종료/없는 작업을 알린다. 클라이언트는 최대2개 SSE와 반복 조회를
  사용하며 오래된 revision을 거부하고 로그아웃 시 자원을 닫는다.
- `POST /jobs/{id}/cancel`: 실행 중에는 취소 요청이며, 프로세스가 정리된 뒤 cancelled이다.
- `POST /jobs/{id}/retry`: 실패·취소·중단 부모와 새 유효 분석으로만 가능하다.
  완료 파일을 다시 만드는 것은 일반 새 생성이다. 원본 영상이 달라지면409이다.
- `GET|HEAD /jobs/{id}/file`: 접근 시 TTL 확인, 열린 정규 파일 핸들과 전송 임대를
  원자적으로 확보한다. 전체200/단일 Range206/불가능한 범위416을 지원한다.
  HEAD로 확인한 뒤 네이티브 다운로드를 시작하며, 클릭은 기기 저장 완료의 증거가 아니다.
- `PATCH /jobs/{id}/retention`, `DELETE /jobs/{id}/file`: 전송 중인 파일을 삭제하지 않는다.
  서버 파일과 기록 삭제는 별도 동작이다. 활성 작업의 기록 삭제는409이다.
- `GET|PATCH /settings`: 언어·테마·MP3 기본 비트레이트 및 읽기 전용 저장소/기능 한도.
  저장한 MP3 기본값은 다음 분석부터 적용되며 이미 큐에 있는 계약은 변경하지 않는다.
- `GET /readiness`: 인증된 사용자의 로컬 작업자/필수 도구/공간 준비 상태.
  `GET /diagnostics`는 선택적 도움말이며 공급자 연결 성공을 추측하지 않는다.

오류는 `{error:{code,message,retryable,action,retry_after_seconds?}}`이며 대기 시간이
있으면 HTTP `Retry-After`도 보낸다. 클라이언트는 HTTP 상태, 복구 종류, 안전한 작업
문맥을 보존한다. HTML 게이트웨이 오류/빈 응답/취소/시간 초과를 JSON 파싱 오류로
숨기지 않는다. 각 카드·설정 작업의 실패를 따로 표시한다.

주요 복구: `UNAUTHORIZED`→로그인, `CSRF_FAILED`→세션 재확인,
`ANALYSIS_EXPIRED|FORMAT_CHANGED`→재분석,
`SOURCE_RATE_LIMITED|LOGIN_THROTTLED`→서버 대기 시간,
`STORAGE_FULL`→사용자가 파일 정리,
`HISTORY_ACTIVE|RETRY_NOT_ALLOWED`→허용된 상태 전이,
`FILE_EXPIRED|FILE_MISSING`→새 작업.

실제 API 본문은 Content-Length 유무와 상관없이64KiB,15초 수신 제한을 적용한다.
Grok 브리지는 실제 incoming Host/Origin을 검증한 뒤에만 루프백으로 번역하며,
상위 버퍼에도 같은64KiB 제한을 적용한다. 개발 출처를 추가하려면
`SEORAP_PREVIEW_ALLOWED_HOSTS`와 `SEORAP_PREVIEW_ORIGINS`에 정확한 호스트/출처를
명시한다. 임의 forwarded 헤더를 신뢰하지 않는다.
