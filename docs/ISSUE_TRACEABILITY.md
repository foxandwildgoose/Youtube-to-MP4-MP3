# 감사 이슈 추적표

기준과 시작 HEAD는 `a83e6d1a73d9ffbcb1b363203de92779779e6082`이며 시작 작업 트리는
깨끗했다. 첨부 명세의60개 ID를 현재 구현에 모두 대조했다. 기존 기능을 새 기능 부재로
다시 주장하거나 overlapping ID를 독립 결함 수로 부풀리지 않는다.

아래는 구현 처분과 검증 연결이다. 정확한 최신 실행 수/명령/스크린샷 및 실행하지 못한
플랫폼별 검사는 [VERIFICATION.md](VERIFICATION.md)가 기준이다. 코드 수정과 특정
플랫폼의 실제 검증 완료는 다르다. 테스트 함수 이름은 parametrized case를 포함한다.

| ID | 처분 | 현재 코드 | 검사/게이트 |
| --- | --- | --- | --- |
| **I01** | 템플릿·기존.env 보존·오류 분리 구현. PowerShell 실제 로컬 실행은 도구 부재로 skipped, CI5.1/7 추가 | `scripts/setup.sh, setup.ps1, .env.example` | setup-runtime.test.mjs; setup-powershell.test.mjs; V01 |
| **I02** | one-shot CHOWN만 부여, 필요한 디렉터리만 초기화; 기존 전체 재귀 소유권 변경 없음 | `docker-compose.yml, scripts/init-volume.sh` | 실제 named volume fresh/reuse + bind mount; V02 |
| **I03** | 보호 기본값·잘못된 boolean 설정 거부·명시적 허용 출처·헤더 번역 전 검사 | `config.py, startup.sh, preview-runtime.py, vite.config.ts, seorap-proxy.ts` | test_invalid_boolean_flags_fail_closed_without_silently_disabling_auth; seorap-preview-policy.test.ts; test_auth_origins_and_bootstrap_once; V03 |
| **I04** | 개인 Compose/별도 Grok 구분; 최신 사용자 요청으로 개인용 비밀번호 입력 제거; Vercel은 미설정 상태 또는 전체 HTTPS 앱 이동 | `docker-compose.override.yml, session-requests.ts, seorap-deployment.ts, seorap-proxy.ts, docker-compose.https.yml` | passwordless backend/client/setup/browser 회귀; VERIFICATION_PASSWORDLESS.md; Vercel function8checks·HTTPS fixture |
| **I05** | API/worker 독립 잠금·소유권·heartbeat 재시작 검사; 빌드 QA 종료 시 zombie 오판 수정 | `scripts/preview-runtime.py, scripts/preview.mjs` | scripts/test_preview_runtime.py; scripts/preview.test.mjs 실제 zombie 및 실제 restart/stop; V06 |
| **I06** | B03과 같은 제어 루프 수정으로 해결; 중복 결함으로 세지 않음 | `worker.py, diagnostics.py` | test_busy_worker_heartbeat_and_housekeeping_beyond_stale_threshold; V06 |
| **I07** | unless-stopped 구현; 호스트 Docker daemon 재시작 실험은 미실행 | `docker-compose.yml, worker.py` | 격리 Compose worker exit/intentional stop; V06 |
| **I08** | linux/amd64만 지원, ARM native 미지원 명시; DENO_DIR writable tmpfs | `Dockerfile, scripts/install-deno.sh, docker-compose.yml` | 공식 SHA256 mismatch/arch 거부 + 실제 read-only 이미지 실행; V02 |
| **I09** | LASTEXITCODE 즉시 검사·readiness 후 성공 안내; PowerShell 로컬 런타임 부재는 skipped | `scripts/setup.ps1` | scripts/setup-powershell.test.mjs; V01 |
| **I10** | B20과 같은 환경변수→PATH 도구 검색; live MP4/MP3 opt-in | `backend/tests/conftest.py, test_live_smoke.py` | 실제 호스트/테스트 이미지 pytest; V21/V22 |
| **I11** | 생성 .vercel/output·runtime bin·transient PID 추적 제거, 로컬 도구 유지, history 재작성 없음 | `.gitignore, .dockerignore, Dockerfile` | clean-source image build; git index; V21 |
| **I12** | B14와 같은64KiB actual-stream 상한; 응답 SSE/file은 스트리밍 | `server/utils/seorap-preview-policy.ts, seorap-proxy.ts` | declared/streamed body-cap tests; V13 |
| **I13** | B16/B18과 연계, preview current+2backup 한도; Compose 회전 별도 | `scripts/run-logged.py, preview-runtime.py` | test_preview_runtime.py rotation/cap checks; V20 |
| **X01** | CLI-only 초기 설정을 정확히 표시; 허용된 loopback browser bootstrap만 폼 제공 | `main.py session/bootstrap, public_models.py, app.tsx` | test_bootstrap_capability_and_cli_default; browser first-run; V03 |
| **B01** | 입력/출력/작업공간/전체/여유 실제 바이트 감시와 실패 정리 | `worker.py _runtime_budgets; engine_runner.py; engine/child.py` | test_silent_growing_engine_is_stopped_by_actual_budget, test_fixture_limit_failure_never_publishes_and_releases_reservation; V05 |
| **B02** | BEGIN IMMEDIATE 입장·예약·멱등성, 전체 workspace 보수적 예약 정책 명시 | `services/jobs.py create_job; services/storage.py reservations; worker.py claim_next` | test_atomic_admission_distinct_and_identical_keys, test_written_workspace_replaces_reservation_and_claim_rechecks; V04 |
| **B03** | 1task executor와 독립 제어 루프/heartbeat/제한된 housekeeping; 동시성1만 허용 | `worker.py serve_forever; config.py; diagnostics.py` | test_busy_worker_heartbeat_and_housekeeping_beyond_stale_threshold; V06 |
| **B04** | 프로세스 그룹 TERM/KILL/reap, 생명주기/시작 시각/namespace 소유권 | `engine_runner.py, worker.py, main.py lifespan` | callback/sqlite failure descendants, actual FFmpeg cancellation, OS SIGTERM/recovery tests; V06 |
| **B05** | 전역 cooldown·영구 next_attempt_at·유한403/재시도 예산 | `worker.py, services/slots.py, services/analysis.py, engine/child.py` | test_worker_429_persists_cooldown_before_other_metadata_starts, test_b17_retry_after_and_global_cooldown_never_shorten; V07 |
| **B06** | 활성 기록409·행 유실시 중단·늦은 실패가 보관 파일 삭제하지 않음 | `services/jobs.py delete_history; worker.py terminal handlers` | test_active_history_and_retry_rejected_without_losing_control, test_missing_authoritative_row_stops_work; V08 |
| **B07** | 원자 TTL/open/lease, 독립 갱신·disconnect 정리 | `services/storage.py open_artifact/leases; main.py file_response` | test_asgi_download_start_interleaves_with_file_lifecycle, test_asgi_disconnect_releases_lease, test_access_time_ttl_pin_and_renewal; V08 |
| **B08** | 조건부 로컬 파일 경계 강화; remote URL exploit을 주장하지 않음 | `services/storage.py descriptor open/publication` | test_exact_subtree_no_follow_filesystem_hardening, test_directory_swap_after_open_keeps_exact_original_inode, test_publication_source_swap_cannot_publish_a_symlink; V09 |
| **B09** | 논리 트랙/표현 분리·결정적 고품질 입력·언어/품질 보존 | `services/format_planner.py, match.py` | test_b09_track_identity_quality_and_language_survive_permutations; V10 |
| **B10** | FPS 선택/실제 ffprobe/좁은 duration 허용 오차 검증 | `services/format_planner.py, media_validate.py` | test_b10_actual_24fps_rejects_promised_60_and_truncation, test_b10_actual_rational_and_variable_average_rate; V11 |
| **B11** | 0/90/180/270 실제 파일·표시 픽셀·복사/회전 변환 계약 | `format_planner.py, match.py, media_validate.py, engine/child.py` | test_b11_real_rotation_copy_and_conversion; V11 |
| **B12** | 입력 exact/approximate/unknown·공유 muxed 1회·출력 추정/예산 별도 | `engine/child.py sanitize_info; format_planner.py` | test_b12_sanitize_provenance_and_no_durable_signed_urls, test_b12_separate_inputs_and_unknown_size; V12 |
| **B13** | 저장128/192/320 새 분석 기본값·기존 큐 계약 불변 | `services/analysis.py; frontend settings` | test_b13_saved_mp3_preference_authoritative_future_analysis; V12 |
| **B14** | urlsplit 예외·모호 query/path·실제 ASGI 바이트/수신 시간 제한 | `request_limits.py, services/url_policy.py, preview policy` | test_actual_asgi_request_limit_before_app, test_asgi_with_dishonest_length_is_bounded, test_url_errors_are_structured; V13 |
| **B15** | 표준 chunked 해독·TLS/DNS/redirect/deadline/size·이미지 검증·bounded cache | `services/safe_http.py; Pillow runtime dependency` | test_standards_http_framing_decodes_equal_images, test_thumbnail_private_mixed_dns_redirect_and_bad_image, test_thumbnail_size_and_truncated_framing; V13 |
| **B16** | 비파괴 transaction migration·참조 보존·메타데이터/로그 상한·연결 close | `db.py, migrations/0002*, storage.py cleanup, CLI/main startup, child.py logs` | migration preservation/rollback, metadata retention, bounded stderr/log regressions; V20 |
| **B17** | 재시도/새 생성 구별·모든 해석 deadline/slot/cooldown·중복추출 제거 | `jobs.py validate_retry_parent; slots.py; worker.py; child.py` | test_b17_slow_metadata_deadline_cannot_outlive_permit, test_b17_direct_selected_download_never_extracts_again; V07 |
| **B18** | component별 bytes·실측 배속 ETA·점진 읽기·단계별 unknown | `engine/child.py progress; worker.py phase reset; JobCard` | test_b18_eta_is_measured_wall_clock, test_b18_incremental_progress_and_bounded_stderr; V17 |
| **B19** | 공개/추가 provider 조건은 지원 범위 밖. 실제 engine 전체 egress confinement은 구현/검증했다고 주장하지 않음 | `README.md, docs/ARCHITECTURE.md, canonical URL/pinned thumbnail boundary` | strict URL/controlled thumbnail DNS+redirect tests; V13 |
| **B20** | 회귀와 live 증거 분리; 허가 URL 없음으로 live MP4/MP3 skipped | `portable tests; Docker test target; CI; browser harness` | full pytest + controller + actual fixture browser, V01–V22 |
| **FE-01** | 복원 활성 작업·반복poll·focus/online 복구 | `job-feed.ts, use-downloader-controller.ts` | job-feed.test.ts recurring/restored/recovery; browser reload/reconnect |
| **FE-02** | 정규화 ID·revision 단조·안정 정렬 | `job-store.ts` | state.test.ts reversed revision/list/event/mutation |
| **FE-03** | 실제 연결 상태·최대2SSE·나머지 반복 조회·자원 정리 | `job-feed.ts` | job-feed.test.ts cap2/bye/logout/late-source events |
| **FE-04** | 중앙401/CSRF 복구·세션 소유 캐시/취소 정리 | `session.ts, api.ts, controller` | api.test.ts unauthorized + session-scope state regressions |
| **FE-05** | HTTP 정보 보존·안전한 파싱·기한/취소·중요 shape 검증 | `api.ts, contracts.ts, public-contracts.generated.ts` | api.test.ts HTTP matrix/timeout/abort/2MiB/HEAD |
| **FE-06** | 작업별 pending/error·중복 클릭 방지·실패 reject | `controller, JobCard, SettingsDialog` | api.test.ts failures + browser file/settings actions |
| **FE-07** | 입력/분석 소스 분리·지연 응답/낡은 closure 거부 | `controller acceptedAnalysis/generation; app.tsx` | state.test.ts stale analysis generations + browser input invalidation |
| **FE-08** | 불확실 intent 저장·동일 키 복구·명시적 새 요청 구분 | `submission.ts, controller` | state.test.ts lost acknowledgement exact key/body replay |
| **FE-09** | 만료 재분석·서버 cooldown 시점·품질 선택 보존 규칙 | `controller expiry/cooldown; ErrorNotice` | state/api timing regressions + browser expired-file flow |
| **FE-10** | auth/analysis/create/playlist/card 개별 대기 | `controller busy flags; app.tsx BusyLabel` | controller tests + browser staged operations |
| **FE-11** | active 독립 조회·검색/필터/페이지/total | `jobs.py list_jobs; controller history; app.tsx` | test_search_paging_filters_include_older_kept_file + browser35history |
| **FE-12** | 동일 제목의 MP4·MP3비트레이트·파일명·실제크기 구분 | `public models/snapshot; components/formatters.ts, JobCard` | media/snapshot contract + browser MP4/MP3 output facts |
| **FE-13** | 완료/삭제/보관 변경 후 debounced refresh, 매 byte 스캔 없음 | `controller aggregate refresh; settings API` | terminal/mutation refresh controller review + browser storage actions |
| **FE-14** | lazy 초기값·시스템 변화·저장 실패 안전·최신 설정 | `preferences.ts, controller, theme-init.js` | state.test.ts storage failure/latest saves + browser reload prefs |
| **FE-15** | semantic facts/errors 현지화·원제목 유지 | `i18n.ts, components/formatters.ts, api locale` | browser ko/en settings/errors/source text |
| **FE-16** | mode-first·모드별 선택·고급 원본오디오/영상변환 | `app.tsx Radix Tabs/selection` | browser MP4/MP3 switching, server choices |
| **FE-17** | 접근 가능한 설정·기본값 실제 적용·선택적 진단·CSP nonce로 대화상자 스타일 허용 | `SettingsDialog, analysis.py effective MP3 preference, main.py, frontend/src/main.tsx` | test_b13_saved_mp3_preference_authoritative_future_analysis + 실제 browser nonce/style 적용 |
| **FE-18** | 사용자 클릭만 읽기·빈값/거부/미지원 피드백·focus | `app.tsx pasteUrl/clear/input` | browser clipboard denial/manual fallback/clear |
| **FE-19** | 이 주소 사용/focus·실패/대체 결과 제거·일괄 시작 없음 | `controller playlist generation; app.tsx` | browser playlist select + backend bounded playlist fixture |
| **FE-20** | 모바일 로그아웃·login current-password·setup new-password | `app.tsx auth forms/mobile signout` | browser320/390/zoom/logout |
| **FE-21** | 실제 keyboard·자동 접근성 검사; 전용 OS screen-reader 수동 검사는 미실행 | `Radix Tabs/Dialog/AlertDialog, labels/focus/styles` | browser keyboard/axe/accessibility tree |
| **FE-22** | 조건부 layout 위험을 실제 합성 콘텐츠로 검증 | `styles.css, metadata/card/history/settings components` | authenticated screenshots320/390/768/1280 and zoom |
| **FE-23** | offline/auth/setup/processing 구별·다시 확인 | `controller retryConnection/refreshStorage, app gate` | browser initial setup/readiness/recovery + API tests |
| **FE-24** | 정당한 download 비율만·bytes/추정/미상·단계간 가짜 전체% 없음 | `JobCard, formatters.ts, engine component progress` | B18 ETA/progress tests + browser |
| **FE-25** | 파괴적 파일 삭제 확인·HEAD 후 native stream·Blob 없음 | `JobCard AlertDialog; api.headFile; controller.download` | api HEAD404/410/401 tests + browser native file/delete/expire |
| **FE-26** | 로그인 화면만의 증거를 대체하는 인증·작업자·미디어·파일 여정 | `focused client modules/tests; scripts/test-downloader-browser.mjs` | full real fixture browser, both builds, V14–V21 |

## 조건부 항목과 남는 운영 경계

- I02/I08의 플랫폼별 권한·CPU 조건은 실제 지원 amd64 이미지에서 검사하며 네이티브 ARM
  지원을 주장하지 않는다. PowerShell과 Docker daemon 재시작 등 미실행 항목은 별도 표시한다.
- B08은 로컬 파일시스템 변조 권한을 가정한 방어이며 URL 폼에서 원격 유출을 입증한 것이 아니다.
- B19의 공개 호스팅/새 provider 전제는 이 요청의 개인 loopback 지원 범위 밖이다.
  canonical 입력과 썸네일 통제가 yt-dlp 전체 요청의 egress 방화벽이라는 주장은 하지 않는다.
- V22는 명시적 허가 URL 미제공으로 skipped다. 합성 처리·화면·로컬 HTTP 다운로드·
  컨테이너 시작을 실제 YouTube 성공으로 대체하지 않는다.
- Grok 외부 리소스의 네트워크 차단은 저장된 허용 목록 초안과 현재 runtime 적용 상태를
  구별하며 소스를 지우거나 테스트에서 숨겨 통과시키지 않는다.
