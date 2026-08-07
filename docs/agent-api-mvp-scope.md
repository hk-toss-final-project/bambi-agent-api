# Agent API MVP 개발 범위

> 이 문서는 전체 기능 명세의 고유 ID를 그대로 사용하며, MVP에서 구현할 항목만 선별한 범위 문서입니다.

## MVP 목표

- 사용자가 선택한 데이터로 Entity·Concept·Schema 구조의 개인 LLM Wiki를 구성한다.
- 웹 클리퍼가 전달한 Frontmatter와 Markdown 원문을 PostgreSQL에 영구 저장한다.
- Personal Wiki Builder Worker가 저장된 클리핑을 Chunk·Embedding·관심사 갱신까지 비동기로 처리한다.
- 개인 Wiki 데이터를 기반으로 사용자 관심사를 분류한다.
- Naver API, NewsAPI, GDELT 데이터를 정기적으로 수집한다.
- 개인 Wiki와 최신 수집 데이터를 결합해 리포트 생성기 콘텐츠를 생성한다.
- 생성 결과를 service-api 및 service-worker가 사용할 수 있도록 제공한다.
- Service 스케줄러의 생성 요청(즉시 또는 `scheduled_at` 예약)을 Agent Worker가 Batch로 처리하고, Service Worker가 준비된 Publish Snapshot을 Batch로 가져가 service-db에 반영한다.

## MVP 구현 현황 체크리스트

> 기준: 2026-08-06. 기능 ID 스캐폴드 함수가 아니라 **실제 런타임 경로**(라우터·서비스·Worker·저장소·Agent)가
> 동작하는지 기준으로 판정했다. 표기: `[x]` 구현 완료, `[x] ⚠️` 핵심 동작은 되지만 제약 있음,
> `[ ] ❌` 미구현, `[ ] ➖` Agent API 범위 아님(service-worker 책임).
>
> **집계: 완료 63 · 부분 8 · 미구현 11 · 범위 외 2 (총 84)**

### 내부 API 인증

- [x] `AUTH-001` Service API 인증 — `Authorization: Bearer`의 opaque 토큰을 검증하고 Swagger 전역 인증에 연결
- [x] `AUTH-002` Service Worker 인증 — Service API와 같은 배포 Secret을 검증하되 별도 기능 경계로 기록

### MCP Personal Access Token

- [x] `KEY-001` API Key 발급 — `wiki:read` 고정 Scope의 `bmb_mcp_` Key를 만들고 원문은 최초 응답에서만 노출
- [x] `KEY-002` API Key 조회 — 인증 사용자의 Key 상태·Prefix·사용 시각을 원문과 Hash 없이 조회
- [x] `KEY-005` API Key 폐기 — 인증 사용자 소유 Key를 멱등하게 영구 폐기
- [x] `KEY-008` API Key Hash 저장 — SHA-256 Hash와 공개 식별 Prefix만 DB에 저장
- [x] `KEY-009` API Key Scope 설정 — Personal Wiki 도구는 `wiki:read` Scope만 허용
- [x] `KEY-014` Personal Wiki 접근 권한 — 검증된 Key의 `principal_id`를 Wiki 사용자 범위로 강제
- [x] `MCP-003` MCP 인증 — Streamable HTTP 요청의 Bearer API Key를 Agent DB Hash와 검증
- [x] `MCP-009` MCP Scope 검증 — `wiki:read`가 없는 Key의 Tool 접근 거부
- [x] `MCP-011` MCP 사용자 권한 검증 — Tool 입력으로 user_id를 받지 않고 인증 주체로 Namespace 결정
- [x] `MCPTOOL-001` Personal Wiki 검색 — 개인 Namespace의 제목·요약·본문 부분 일치, 무관한 최신 문서 fallback 없음
- [x] `MCPTOOL-002` Personal Wiki 문서 조회 — search가 반환한 ID의 Markdown·출처를 같은 사용자 범위에서 조회

### Service API 연동

- [x] `SVC-001` 사용자 컨텍스트 전달 — `user_context_snapshots` 저장, `STALE_CONTEXT_VERSION` 검증
- [x] `SVC-002` 웹 클리핑 처리 요청 — 원본·Version·Job 한 Transaction Commit 후 202
- [x] `SVC-003` URL 처리 요청 — URL Head 저장 + `personal_wiki_url` 수집 Job 등록 + 상주 `url-collection` Worker의 Jina 본문 Version 저장·후속 Wiki Job 연결
- [x] `SVC-004` 위키마킹 처리 요청 — 생성 후보 본문을 `content_mark` 원본 Version으로 물질화 후 기존 `personal_wiki_build` Job으로 처리 (별도 Handler 불필요, 2026-07-27 구현. 대상 콘텐츠 없으면 404)
- [x] `SVC-006` 사용자 피드백 전달 — 좋아요·숨김·신고 신호를 `feedback` 이벤트로 멱등 저장(Wiki 문서 미생성). 다음 재계산 때 INT-005가 점수 반영 (2026-07-27 구현)
- [x] `SVC-008` 콘텐츠 생성 요청 — `generation_requests` + `report_generation` Job 멱등 등록, `scheduled_at` 예약 실행 지원
- [x] `SVC-013` Agent Job 상태 조회
- [x] `SVC-014` Agent 결과 조회 — 미완료 시 `JOB_RESULT_NOT_READY`
- [x] `WSE-001` 웹 클리핑 이벤트 수신 — `wiki_source_events` + Frontmatter 필드 저장
- [x] `WSE-011` 이벤트 중복 처리 방지 — `user_id + source_event_id` 식별 및 DB Unique·Upsert 적용
- [x] `WSE-013` 이벤트 처리 상태 관리 — Claim·완료·실패 시 Source Event 상태 동기화
- [x] `WSE-014` 온보딩 관심사 시드 수신 — 온보딩 컨텍스트 수신 시 선택 Category·Topic을 시드 Markdown으로 합성해 `onboarding_seed` 원본·Wiki Build Job으로 접수한다. Builder는 `source_metadata.labels`를 LLM 없이 결정적으로 Concept로 만든 뒤 기존 Build·Snapshot·INT-011 경로를 재사용한다. 선택 내용 기반 멱등, best-effort(컨텍스트 저장과 분리)
- [x] `PWIKI-006` 개인 Wiki 문서 버전 관리 — 원본 Version·Wiki Version·Build Snapshot 분리 보존
- [x] `PWIKI-007` Wiki 문서 출처 추적 — `wiki_document_sources` 연결
- [ ] `PWIKI-011` Wiki 문서 정규화 — ❌ 독립 정규화 기능 미구현. Frontmatter 저장은 `WSE-001/DB-002`, Wiki 구조 변환은 `WBA-003`이 담당하며 기존 항등 위임 함수는 스텁으로 복원
- [x] `DB-002` Wiki Source Event·원본 저장
- [x] `DB-003` 개인 LLM Wiki 문서 저장

### 사용자 개인 LLM Wiki

- [x] `PWIKI-002` 개인 Wiki 문서 생성 — Entity·Concept·Schema 증분 생성
- [x] `PWIKI-003` 개인 Wiki 문서 조회 — 목록·상세·Build·Graph·연결 상위 Node(top-nodes)
- [x] `PWIKI-005` 개인 Wiki 문서 삭제 — soft-delete + Chunk 검색 제외 (동기·멱등). 삭제 정책은 Service 소유, `pwiki_005` facade는 영속화 계층 `delete_wiki_document_and_record_event`에 위임 (WBA-015와 동일 실행 경로 공유). D1 잠정: 재등장 시 기본 부활, tombstone 없음
- [x] `PWIKI-008` Wiki 문서 중복 제거 — ⚠️ 같은 `document_key` Upsert·병합은 구현, 유사 문서 의미 판단은 LLM 프롬프트에 위임
- [x] `PWE-001` 개인 Wiki 문서 Chunking
- [x] `PWE-002` Chunk 저장 — `wiki_chunks` 멱등 Upsert
- [ ] `PWE-004` Embedding 생성 — ❌ 보류(2026-07-20 결정). 활용처(Vector 검색)가 없어 실행 경로에서 제외했으며 생성 유틸(`generate_wiki_embeddings`)은 재도입 대비로 유지
- [ ] `PWE-005` Embedding 저장 — ❌ 보류(위와 동일). `wiki_embeddings` 스키마와 저장 함수는 유지
- [x] `PRAG-003` Hybrid Search — ⚠️ FTS·키워드 검색만 결합, pgvector 의미 검색은 미연결
- [x] `PRAG-006` 개인 Wiki Context 구성 — Report Builder 입력 Context(P1, P2 참조) 조립
- [x] `PRAG-007` Citation 연결 — `citations`에 문서 Version·Chunk 연결

### DB 기반 관심사 분류

- [x] `INT-001` 관심사 Topic 추출 — 활성 Wiki의 Entity·Concept 노드를 후보로 삼고 관계 유형 가중 연결 수(degree)로 정렬 (2026-07-23 텍스트 토큰화 폐기, 로직 소유 `domain/interests`)
- [ ] `INT-002` 관심사 Category 분류 — ➖ **MVP 범위에서 제외 (2026-08-04 팀 결정).** Category는 온보딩에서 신규 사용자의 관심사를 대략 파악하는 용도이며, **추출된 관심 Topic을 Category로 다시 묶을 필요는 없다**는 결론. 상세는 §3 참고
- [x] `INT-005` 관심사 점수 계산 — 2층 계산(2026-07-27 병합). ① 기본 점수: 근거 원문의 수·종류(행동 강도)와 반감기 감쇠(최신성, 90일)를 INT-001 구조 가중치에 곱한다. ② 행동 보정: 좋아요·숨김 신호에 시간 감쇠(반감기 14일)를 적용해 기본 점수에 더하고, Wiki에 없는 Topic도 양의 신호가 쌓이면 행동 전용 후보로 추가한다. 신호 가중치·신호 반감기는 D2 잠정값. 로직 소유 `domain/interests`
- [x] `INT-011` 관심사 프로필 재계산 — Wiki Build 완료 시 자동 재계산(`run_personal_wiki_build` 훅, 실패해도 Build 결과 유지) + 수동 rebuild API. 행동 신호가 없어도 기본 점수는 항상 계산한다. 오케스트레이션 로직 소유 `domain/interests`
- [x] `INT-012` 관심사 범주 묶음 구성 — 활성 관심사 하나와 근거 Wiki 문서의 1홉 연결 노드를 특정 관심분야 리포트의 검색 범주로 고정한다. 상세는 `interest-bundle-report-design.md`

### 외부 데이터 자동 수집

- [x] `COL-001` RSS 수집 — Google News RSS 검색 Provider (자격 증명 불필요)
- [x] `COL-002` Naver API 수집 — Adapter 구현 (자격 증명 필요)
- [x] `COL-003` GDELT 수집
- [x] `COL-004` NewsAPI 수집
- [x] `COL-005` SNS 수집 — YouTube 영상 검색·Reddit 공개 RSS 검색 (자격 증명 불필요). 2026-07-29 범위 추가: 키워드 비서가 쓰던 Provider 구현(`features/youtube.py`·`features/reddit.py`)을 수집 Worker와 수집 스케줄에 연결했다. 뉴스와 성격이 다르고 Reddit은 비인증 레이트리밋이 빡빡해 기본 Provider 목록에서는 제외하고, Source로 등록했을 때만 수집한다
- [x] `GSP-004` API 응답 정규화 — Provider 공통 문서 구조로 변환
- [x] `GSP-006` 문서 중복 제거 — URL 기준 멱등 Upsert
- [x] `GSP-015` 개인 Wiki 자동 반영 금지 — Global Namespace 분리 저장
- [x] `SCH-001` RSS 수집 스케줄 — Google News RSS(`google_news`, COL-001) 정기 수집. 2026-07-28 범위 추가: 영문 키워드에서 가장 정확한 Provider인데(실측 'Cloudflare' 수집 시 Naver 10건 중 관련 3건, google_news 5건 전부 관련) 스케줄에서 빠져 있었다. **명세의 "RSS Source"는 임의 피드 주소를 뜻하지만 이 구현은 키워드 검색이다** — 임의 피드 수집이 필요해지면 별도 Provider로 추가한다. 원본 URL 디코딩 때문에 키워드당 12초쯤 더 걸린다
- [x] `SCH-002` Naver API 수집 스케줄 — 독립 Scheduler 프로세스(`scheduler/main.py`)가 tick마다 `agent.global_sources`의 `schedule_cron`·`keywords`를 읽어 실행 차례가 된 Source만 수집 Worker(WORKER-001)로 넘긴다. 판정 순서는 ① Cron 도달 ② 키워드 존재 ③ `quota_policy.daily_max_runs`
- [x] `SCH-003` GDELT 수집 스케줄 — SCH-002와 동일한 판정·실행 규칙
- [x] `SCH-004` NewsAPI 수집 스케줄 — 수집 Worker에 `newsapi` Provider(COL-004) 연결 포함. 무료 플랜 호출 한도(일 100회)가 낮아 기본 Provider 목록에서는 제외하고 `quota_policy.daily_max_runs`와 함께 쓴다. (참고: MVP 목록 외 `SCH-009` Wiki Build 조용 시간 트리거는 구현됨)
- [x] `SCH-017` 스케줄 등록 — `POST /internal/v1/collection-schedules` (멱등 Upsert, Cron·키워드 검증)
- [x] `SCH-018` 스케줄 수정 — `PATCH /internal/v1/collection-schedules/{source_key}` (부분 수정, 다음 tick부터 반영)
- [x] `SCH-019` 스케줄 중지 — `POST .../{source_key}/pause` (설정 보존, status만 paused)
- [x] `SCH-020` 스케줄 재개 — `POST .../{source_key}/resume`
- [x] `SCH-021` 스케줄 수동 실행 — `POST .../{source_key}/run` (Cron 주기·일일 한도·중지 상태를 모두 건너뛰고 등록된 키워드를 전부 즉시 수집. 이 조건들은 "알아서 도는 수집"을 통제하는 장치이므로 관리자가 명시한 실행까지 막지 않는다. 실행 이력은 남아 이후 정기 실행의 `runs_today`에는 반영된다). 2026-07-29 범위 추가: 키워드를 바꾼 뒤 다음 tick(최대 주기만큼)을 기다려야 적재를 확인할 수 있어 점검이 막혔다. 수집 규칙은 정기 실행과 같은 구현을 공유하고 동기로 실행해 결과를 그대로 돌려준다
- [x] `SCH-022` 스케줄 이력 조회 — `GET /internal/v1/collection-schedules` (현재 설정 + 최근 실행 이력)

### 리포트 생성기 (Report Builder)

- [x] `REPORT-001` 콘텐츠 생성 요청 — 운영 등록 + dev 즉시 실행
- [x] `REPORT-004` 개인 Wiki 검색
- [x] `REPORT-005` Global Source 검색 — 키워드 비서(`agent/assistant`)의 실시간 수집(뉴스 RSS·YouTube·Reddit) 연결
- [x] `REPORT-006` 생성 자료 선별 — 개인 Wiki 맥락 + 실시간 근거를 합쳐 생성 입력을 고른다
- [x] `REPORT-008` 콘텐츠 요약 생성
- [x] `REPORT-009` 콘텐츠 본문 생성
- [x] `REPORT-010` 콘텐츠 태그 생성 — 생성된 내용에서 검색·추천용 태그를 뽑는다. **별도 LLM 호출을 쓰지 않고** 본문 생성 응답에 `tags`를 함께 받는다(추가 비용·지연 없음, 제목·본문과 같은 근거 기반). 발행 페이로드에는 `content_tags`로 싣고, 기존 `tags`(생성 요청 topic)는 그대로 둔다 — Service가 `card_interest_tags`로 소비 중이라 의미를 바꾸면 계약이 깨진다(2026-08-05 이송우 협의).
- [x] `REPORT-011` 콘텐츠 Citation 생성 — P1·G1 참조 검증 포함
- [x] `REPORT-012` 사용자 개인화 적용 — 언어 반영 구현. **차단(비선호) 필터는 MVP 범위에서 제외**(입력 UX 부재 + 피드백 반영 위치 미확정, 2026-07-24 결정). 관련 컬럼(`blocked_interest_ids`·`blocked_source_ids`)은 스키마에만 남기고 검색·생성에는 적용하지 않는다.
- [x] `REPORT-018` 생성 콘텐츠 후보 저장 — `generation_runs`·`generated_content_candidates`
- [x] `REPORT-020` 콘텐츠 완료 이벤트 — `CONTENT_READY`를 `event_outbox`에 기록까지 구현. **Event Bus 발행 Relay(`WORKER-012`)는 보류**(2026-07-24 결정): 이벤트를 받는 쪽이 service-api(full stack 팀)라 전달 방식·payload 형식 합의와 양쪽 동시 테스트가 필요하다. full stack 연동 시점에 함께 진행한다.
- [x] `REPORT-021` 자동 Wiki 편입 금지 — 생성 결과는 후보 테이블에만 저장

### 변경점 추적 (Change History)

> 요청 토글(`change_history_enabled`)이 켜졌을 때만 도는 경로다. 기본값은 꺼짐이며,
> 꺼진 요청은 기존 generate 경로와 100% 동일하게 동작한다.

- [x] `CHG-001` 변경점 추적 오케스트레이션 — Supervisor가 첫 실행·변화 없음·워커 재작업 세 경로를 판단한다. LLM을 부르지 않는 결정적 판단 노드
- [x] `CHG-002` 팩트 추출·과거 대조 — `search_base_facts` 도구 하나를 쥔 자율 에이전트. 첫 실행이면 과거 대조 부분만 생략하고 출력 형식은 유지
- [x] `CHG-003` 종합 브리핑·타임라인 생성 — Overview와 타임라인을 한 호출로 생성(같은 팩트셋의 다른 뷰라 나누면 중복 서술이 생긴다)
- [x] `CHG-004` 파급효과·행동 지침 추론 — Compose와 분리. 추론 난이도가 높아 섞으면 이쪽이 대충 처리된다. `CHANGE_HISTORY_IMPACT_MODEL`로 이 노드만 상향 가능
- [x] `CHG-005` 델타 정합성 검증 — 갱신 대상 팩트 ID의 실재·소속, 타임라인 날짜 타당성, overview·implications의 인용 마커 존재를 코드로 검사(LLM 없음). 마커가 없으면 그 워커만 1회 재작업 — 프롬프트로 부탁만 해서는 지켜지지 않았다(2026-08-05 실측 0.692 → 규칙 강화 후 0.923)
- [x] `CHG-006` 델타 보고서 조립 — 섹션 4개를 코드로 이어 붙인다. LLM 재작성을 쓰지 않아 before/after 수치가 훼손되지 않는다. 조립 후 기존 quality 검사를 재사용하되 "변화 없음" 보고서는 제외한다(팩트가 없어 인용 0개가 정상인데 quality는 무조건 `no_citations`로 보기 때문)

### Worker 및 서비스 반영

- [x] `WORKER-001` Global Source Collector Worker — ⚠️ 수집·저장은 dev API 동기 실행만, 상주 Worker 없음
- [x] `WORKER-002` Personal Wiki Builder Worker — 단발·상주(Loop) 모드 CLI
- [x] `WORKER-003` Report Builder Generation Worker — 단발·상주(Loop) 모드 CLI, `SKIP LOCKED` Batch Claim (dev API와 같은 Handler 체인)
- [ ] `SW-001` Content Ready 이벤트 수신 — ➖ service-worker(Spring) 책임, Agent API 범위 아님
- [x] `SW-004` Publish Snapshot 조회 — 단건 조회 + Lease Batch Claim
- [ ] `SW-007` service-db 콘텐츠 Upsert — ➖ service-worker 책임
- [x] `SW-009` 발행 완료 ACK — 단건 + 부분 성공 Batch ACK
- [x] `WBA-001` Incremental Wiki Build
- [x] `WBA-003` Wiki 문서 정규화 — Build 파이프라인에 포함
- [x] `WBA-015` Wiki 삭제 반영 — delete 이벤트 기록 + 문서 soft-delete + Chunk 검색 제외 (동기·멱등, 2026-07-27 구현. 실행 경로는 삭제 API→Repository이며 wba_015는 커넥션 보유 호출자용 facade. D1 잠정: 재등장 시 기본 부활, tombstone 없음)
- [x] `JOB-001` Agent Job 생성 — 원본 저장과 같은 Transaction
- [x] `JOB-002` Agent Job 조회
- [x] `JOB-006` Agent Job 진행률 관리 — ⚠️ progress 값만 갱신(0→5→100), 단계별(정규화·Chunking·Embedding) 기록 없음
- [x] `JOB-007` Agent Job 결과 연결 — wiki_version_id·affected_documents·chunk_count
- [x] `JOB-010` Agent Job Idempotency
- [x] `WC-001` Queue Job Consume — 상주 소비 루프
- [x] `WC-002` Job Claim — `FOR UPDATE SKIP LOCKED` + Lease
- [x] `WC-006` Retry 정책 — retryable 실패 시 지연 후 queued 복귀
- [ ] `WC-009` Idempotency 처리 — ❌ Worker 공통 멱등 처리 기능 미구현. 개별 DB·Job 경계의 Unique·Upsert는 유지하며 기존 항등 위임 함수는 스텁으로 복원
- [x] `WC-013` Concurrency 제어 — ⚠️ Batch Claim 크기 설정만 있고 LLM·Embedding 동시 실행 제한은 순차 처리로 대체
- [x] `DB-004` 개인 Wiki Chunk 저장
- [x] `DB-005` 개인 Wiki Embedding 저장
- [x] `DB-026` Agent Job 저장 — Claim·Lease·Attempt 이력

## 0. 내부 API 인증

| ID | 기능 | 설명 |
|---|---|---|
| AUTH-001 | Service API 인증 | Service API가 제시한 내부 Bearer 토큰을 검증한다. |
| AUTH-002 | Service Worker 인증 | Service Worker가 제시한 내부 Bearer 토큰을 검증한다. |

Swagger UI, `/wiki-graph`, `/dev/graphs` 같은 개발 화면은 토큰 없이 열 수 있지만,
`/internal/v1/**` API 실행에는 `AGENT_INTERNAL_TOKEN`과 일치하는 Bearer 토큰이
필요합니다. `/wiki-graph`는 Swagger에 영속 저장된 `InternalBearer` 토큰 또는
화면에서 한 번 입력해 저장한 토큰을 Graph API 요청 헤더에 적용합니다. 서버 Secret을
HTML이나 URL에 삽입하지 않습니다. `/system/*` 상태 확인 API는 인증 대상에서
제외합니다.

## 1. Service API 연동

| ID | 기능 | 설명 |
|---|---|---|
| SVC-001 | 사용자 컨텍스트 전달 | 서비스 사용자 설정을 Agent 컨텍스트로 전달한다. |
| SVC-002 | 웹 클리핑 처리 요청 | 클리핑 Markdown을 영속 저장하고 Personal Wiki Builder Job을 등록한다. |
| SVC-003 | URL 처리 요청 | 입력된 URL을 개인 Wiki 처리 작업으로 전달한다. |
| SVC-004 | 위키마킹 처리 요청 | 사용자가 선택한 콘텐츠의 Wiki 편입을 요청한다. |
| SVC-006 | 사용자 피드백 전달 | 좋아요, 숨김, 신고 등의 신호를 전달한다. |
| SVC-008 | 콘텐츠 생성 요청 | 리포트 생성기의 콘텐츠 생성을 요청한다. |
| SVC-013 | Agent Job 상태 조회 | 비동기 작업 상태를 조회한다. |
| SVC-014 | Agent 결과 조회 | 생성 및 처리 결과를 Agent API에서 조회한다. |

### 웹 클리핑 수신·영속 저장

| ID | 기능 | 설명 |
|---|---|---|
| WSE-001 | 웹 클리핑 이벤트 수신 | title, source, author, published, created, description, tags와 Markdown 본문을 수신한다. |
| WSE-011 | 이벤트 중복 처리 방지 | 사용자와 source_event_id 조합으로 동일 클리핑의 중복 저장·Job 생성을 막는다. |
| WSE-013 | 이벤트 처리 상태 관리 | 클리핑의 received, processing, completed, failed 상태를 Worker 처리와 동기화한다. |
| WSE-014 | 온보딩 관심사 시드 수신 | 온보딩에서 고른 Category·Topic을 시드 Markdown 문서로 합성해 개인 Wiki 반영 후보로 수신한다. |
| PWIKI-006 | 개인 Wiki 문서 버전 관리 | 원본 변경 이력과 생성된 Wiki 변경 이력을 각각 Version으로 관리한다. |
| PWIKI-007 | Wiki 문서 출처 추적 | 생성된 Wiki Version과 참고한 원본 Version의 관계를 보존한다. |
| PWIKI-011 | Wiki 문서 정규화 | Frontmatter와 Markdown 원본을 읽어 LLM Wiki 문서 구조로 변환한다. |
| DB-002 | Wiki Source Event·원본 저장 | 요청 상태는 wiki_source_events에, Frontmatter와 Markdown은 user_source_documents 계열에 영속 저장한다. |
| DB-003 | 개인 LLM Wiki 문서 저장 | Worker가 만든 Entity·Concept·Schema를 wiki_documents·wiki_document_versions에 저장하고 원본·문서 관계를 연결한다. |

클리핑 API는 DB Transaction이 Commit된 뒤에만 202 Accepted를 반환합니다. Agent API가
Markdown 저장에 실패했는데 Job만 접수하거나, 인메모리에만 저장한 상태로 성공을
반환하는 구현은 MVP 완료로 보지 않습니다.

## 2. 사용자 개인 LLM Wiki

| ID | 기능 | 설명 |
|---|---|---|
| PWIKI-002 | 개인 Wiki 문서 생성 | 사용자가 선택한 데이터를 Wiki 문서로 변환한다. |
| PWIKI-003 | 개인 Wiki 문서 조회 | 사용자의 Wiki 문서 목록과 상세 내용을 조회한다. |
| PWIKI-005 | 개인 Wiki 문서 삭제 | 사용자가 제거한 데이터를 Wiki 검색 대상에서 제외한다. |
| PWIKI-008 | Wiki 문서 중복 제거 | 동일하거나 유사한 개인 Wiki 문서를 중복 제거한다. |
| PWE-001 | 개인 Wiki 문서 Chunking | Wiki 문서를 의미 단위 Chunk로 분할한다. |
| PWE-002 | Chunk 저장 | 생성된 Chunk를 문서 Version과 연결해 PostgreSQL에 저장한다. |
| PWE-004 | Embedding 생성 | 개인 Wiki Chunk의 Vector를 생성한다. |
| PWE-005 | Embedding 저장 | 사용자별 Vector 검색 저장소에 Embedding을 저장한다. |
| PRAG-003 | Hybrid Search | Keyword와 Vector 검색 결과를 결합한다. |
| PRAG-006 | 개인 Wiki Context 구성 | LLM 입력에 사용할 개인 Wiki Context를 구성한다. |
| PRAG-007 | Citation 연결 | 생성 결과와 참조한 개인 Wiki 문서를 연결한다. |

### 개인 Wiki Graph 조회

- `PWIKI-003`은 현재 Entity·Concept 문서 Version과 `wiki_document_relations`를
  Node·Edge Graph로 조회합니다.
- Graph 응답은 사용자 Namespace의 문서만 포함하고 PostgreSQL RLS 사용자 Scope를
  함께 적용합니다.
- 내부 데이터 API는 `GET /internal/v1/users/{user_id}/wiki/graph`, 시각화 페이지는
  `GET /wiki-graph?user_id={user_id}`로 제공합니다.
- 페이지는 검색, Entity·Concept 필터, 확대·축소·이동·Node Drag와 Markdown 상세
  보기를 제공하며 별도의 브라우저 저장소를 지식 원본으로 사용하지 않습니다.

### Obsidian LLM Wiki 구조 계약

- Entity는 입력에서 발견한 고유 대상별로 `entities/{document_key}.md` 한 개를 유지합니다.
- 같은 `document_key`의 Entity가 이미 있으면 새 문서를 만들지 않고 기존 `wiki_documents`에 새 `wiki_document_versions`를 추가합니다.
- Concept은 둘 이상 Entity에서 반복되는 설계 패턴일 때만 `concepts/{document_key}.md`로 생성합니다. 단일 Entity 전용 설명은 Entity 문서에 남깁니다.
- 기존 Concept과 70% 이상 겹치는 패턴은 새 문서로 만들지 않고 기존 Concept을 갱신합니다. 의미 유사도는 Worker가 판단하고 DB는 결과만 보존합니다.
- Schema는 사용자 Namespace당 `schema/schema.md` 하나만 존재하며, Entity 추가·삭제나 관계 변경 시 새 Version을 생성합니다.
- 완성 Markdown은 YAML Frontmatter를 포함해 `wiki_document_versions.normalized_content`에 저장합니다.
- `wiki_document_relations`는 Entity·Concept 관계를, `wiki_version_documents`는 특정 Wiki Build의 문서 Version·파일 경로 구성을 보존합니다.

## 3. DB 기반 관심사 분류

| ID | 기능 | 설명 |
|---|---|---|
| ID | 기능 | 설명 |
|---|---|---|
| INT-001 | 관심사 Topic 추출 | 개인 Wiki와 사용자 행동에서 관심 주제를 추출한다. |
| ~~INT-002~~ | ~~관심사 Category 분류~~ | **범위 제외** — 아래 참고 |
| INT-005 | 관심사 점수 계산 | 사용자 행동 강도와 최신성을 기반으로 점수를 계산한다. |
| INT-011 | 관심사 프로필 재계산 | Wiki 변경 시 관심사 구조와 점수를 다시 계산한다. |
| INT-012 | 관심사 범주 묶음 구성 | 활성 관심사와 Wiki 1홉 연결 노드를 리포트 검색 범주로 구성한다. |

### INT-002를 범위에서 뺀 이유 (2026-08-04 결정)

**Category는 온보딩 전용이다.** 가입 직후에는 Wiki가 비어 있어 관심사를 추출할
수 없으므로, 사용자에게 직접 물어 대략의 관심 방향을 잡는 데 쓴다. Wiki가
쌓인 뒤에는 추출된 Topic 자체가 더 구체적이므로 **이를 다시 Category로 묶을
이유가 없다.**

착수 전 실측에서 확인한 사실들도 같은 방향을 가리켰다.

| 확인 | 내용 |
|---|---|
| 분류표 사용처 | `bambi/docs/interest-taxonomy.json`(카테고리 8·토픽 44, v1.0.0-draft)을 **코드에서 참조하는 곳이 없다** |
| 온보딩 화면 | `service-web/constants/interests.ts`에 **별도 6개 그룹이 하드코딩**돼 있고 분류표와 목록이 다르다 |
| 저장 형태 | `/api/interests`는 **name 문자열만 저장**하며 Category 필드가 없다. 화면의 그룹은 표시 전용이라 전송되지 않는다 |
| 키워드 매칭 | 분류표 `keywords`로 실제 관심사 40건을 대조하니 **1건만 맞았고 그마저 오답**(`DataGrip` → `webtoon_anime`, keywords의 `IP`가 부분 일치) |

마지막 항목이 특히 분명하다. 분류표 `keywords`는 "생성형 AI"·"금리" 같은 일반
주제어인데 추출된 관심사는 "SK하이닉스"·"ADR 상장" 같은 고유명사라 성격이
다르다. 매핑하려면 관심사마다 LLM을 호출해야 하는데, **그렇게 얻은 Category를
쓸 곳이 없다.**

`domain/interests/features/classification.py`의 `int_002` 스텁은 향후 재도입에
대비해 유지한다. 컨텍스트의 `selected_category_ids`·`selected_topic_ids`
(Migration 0009)는 온보딩 선택을 보존하는 별개 경로이므로 그대로 둔다.

## 4. 외부 데이터 자동 수집

| ID | 기능 | 설명 |
|---|---|---|
| COL-001 | RSS 수집 | Google News RSS 검색 피드에서 신규 콘텐츠를 수집한다. |
| COL-002 | Naver API 수집 | 설정된 키워드로 Naver API 데이터를 수집한다. |
| COL-003 | GDELT 수집 | 글로벌 뉴스와 이벤트 데이터를 수집한다. |
| COL-004 | NewsAPI 수집 | 뉴스 기사와 관련 메타데이터를 수집한다. |
| COL-005 | SNS 수집 | 허용된 SNS 공개 데이터(YouTube·Reddit)를 수집한다. |
| GSP-004 | API 응답 정규화 | Source별 응답을 공통 문서 구조로 변환한다. |
| GSP-006 | 문서 중복 제거 | 동일 URL과 유사 문서를 중복 제거한다. |
| GSP-015 | 개인 Wiki 자동 반영 금지 | 수집 데이터를 사용자 선택 없이 개인 Wiki에 반영하지 않는다. |
| SCH-001 | RSS 수집 스케줄 | RSS Source 수집 작업을 정기 등록한다. |
| SCH-002 | Naver API 수집 스케줄 | Naver API 수집 작업을 정기 등록한다. |
| SCH-003 | GDELT 수집 스케줄 | GDELT 수집 작업을 정기 등록한다. |
| SCH-004 | NewsAPI 수집 스케줄 | NewsAPI 수집 작업을 정기 등록한다. |
| SCH-017 | 스케줄 등록 | 새로운 정기 작업을 등록한다. |
| SCH-018 | 스케줄 수정 | 기존 작업의 실행 주기를 변경한다. |
| SCH-019 | 스케줄 중지 | 정기 작업 실행을 일시 중지한다. |
| SCH-020 | 스케줄 재개 | 중지된 정기 작업을 다시 활성화한다. |
| SCH-021 | 스케줄 수동 실행 | 관리자가 정기 작업을 즉시 실행한다. |
| SCH-022 | 스케줄 이력 조회 | 스케줄별 실행 결과와 상태를 조회한다. |

> SCH-021은 2026-07-29에 MVP 범위로 추가했다. 주기를 바꾸거나 키워드를 고친 뒤
> 실제로 적재되는지 확인하려면 다음 tick까지 기다려야 했는데, 주기가 길수록
> 점검이 사실상 막혔다. Service·운영이 같은 창구에서 즉시 실행할 수 있게 한다.

> SCH-017·018·019·020·022는 2026-07-28에 MVP 범위로 추가했다. 수집 Scheduler를
> Agent 서버가 직접 돌리기로 하면서(기존 협의안은 Service가 Job을 발행하는
> 방향이었다), **Service가 수집 주기를 조정할 창구**가 필요해졌기 때문이다.
> 스케줄 정책의 결정권은 여전히 Service에 있고 Agent는 실행만 담당한다.
> [global-collection-scheduling-proposal.md](archive/2026-07/global-collection-scheduling-proposal.md)
> §4.1의 발행 주기 결정은 이 API로 Service가 직접 넣는 것으로 대체된다.

## 5. 리포트 생성기 (Report Builder)

| ID | 기능 | 설명 |
|---|---|---|
| REPORT-001 | 콘텐츠 생성 요청 | 사용자와 주제에 맞는 콘텐츠 생성 요청을 처리한다. |
| REPORT-004 | 개인 Wiki 검색 | 사용자의 관심사와 기존 지식을 검색한다. |
| REPORT-005 | Global Source 검색 | 최신 외부 자료와 근거를 검색한다. |
| REPORT-006 | 생성 자료 선별 | 콘텐츠 생성에 사용할 자료를 선별한다. |
| REPORT-008 | 콘텐츠 요약 생성 | 피드와 미리보기에 사용할 요약을 생성한다. |
| REPORT-009 | 콘텐츠 본문 생성 | 플랜과 유형에 맞는 본문을 생성한다. |
| REPORT-010 | 콘텐츠 태그 생성 | 콘텐츠 검색과 추천에 사용할 태그를 생성한다. |
| REPORT-011 | 콘텐츠 Citation 생성 | 본문 주장과 참조한 자료를 연결한다. |
| REPORT-012 | 사용자 개인화 적용 | 관심사, 언어를 반영한다. (비선호/차단 설정은 MVP 제외) |
| REPORT-018 | 생성 콘텐츠 후보 저장 | 발행 전 콘텐츠를 agent-db에 저장한다. |
| REPORT-020 | 콘텐츠 완료 이벤트 | 생성 완료 사실을 Integration Event로 발행한다. |
| REPORT-021 | 자동 Wiki 편입 금지 | 생성된 콘텐츠를 사용자 선택 없이 개인 Wiki에 넣지 않는다. |

### 5-1. 변경점 추적 (Change History)

| ID | 기능 | 설명 |
|---|---|---|
| CHG-001 | 변경점 추적 오케스트레이션 | Supervisor가 상태를 보고 워커 경로와 재작업을 결정한다. |
| CHG-002 | 팩트 추출·과거 대조 | 오늘 자료에서 팩트를 뽑고 도구로 과거 기록과 대조해 신규·갱신·중복을 가른다. |
| CHG-003 | 종합 브리핑·타임라인 생성 | 정제된 팩트로 과거 맥락을 잇는 브리핑과 절대 날짜 타임라인을 만든다. |
| CHG-004 | 파급효과·행동 지침 추론 | 정제된 팩트로 시장·트렌드 파급효과와 행동 지침을 추론한다. |
| CHG-005 | 델타 정합성 검증 | 갱신 대상 팩트 ID의 실재·소속, 타임라인 날짜 타당성, 서술의 인용 마커 존재를 코드로 검증한다. |
| CHG-006 | 델타 보고서 조립 | 검증을 통과한 출력에 섹션 헤더를 붙여 단일 markdown으로 조립한다. |

## 6. Worker 및 서비스 반영

| ID | 기능 | 설명 |
|---|---|---|
| WORKER-001 | Global Source Collector Worker | 외부 데이터를 수집하고 Global Source Pool에 저장한다. |
| WORKER-002 | Personal Wiki Builder Worker | 사용자 선택 데이터를 개인 Wiki로 구성한다. |
| WORKER-003 | Report Builder Generation Worker | 생성 Job Batch를 점유하고 제한된 동시성으로 개인화 콘텐츠를 생성한다. |
| SW-001 | Content Ready 이벤트 수신 | 발행 가능한 콘텐츠 이벤트를 소비한다. |
| SW-004 | Publish Snapshot 조회 | Agent API에서 단건 Snapshot을 조회하거나 준비된 Snapshot Batch를 Claim한다. |
| SW-007 | service-db 콘텐츠 Upsert | Batch의 각 콘텐츠 발행본을 멱등하게 저장하거나 갱신한다. |
| SW-009 | 발행 완료 ACK | 단건 또는 Batch의 항목별 service-db 반영 결과를 Agent API에 알린다. |

### Personal Wiki Builder Worker 구현 범위

| ID | 기능 | 설명 |
|---|---|---|
| WBA-001 | Incremental Wiki Build | 새로 저장된 사용자 원본 Version만 증분 처리한다. |
| WBA-003 | Wiki 문서 정규화 | 저장된 Markdown과 Metadata를 Chunking 가능한 공통 구조로 정리한다. |
| WBA-015 | Wiki 삭제 반영 | 삭제된 사용자 원천과 파생 데이터를 제거한다. |
| JOB-001 | Agent Job 생성 | 클리핑 저장 Transaction에서 Personal Wiki Build Job을 함께 생성한다. |
| JOB-002 | Agent Job 조회 | API와 Worker가 클리핑 Job 상태와 진행률을 조회한다. |
| JOB-006 | Agent Job 진행률 관리 | 정규화, Chunking, Embedding, 관심사 갱신 단계를 기록한다. |
| JOB-007 | Agent Job 결과 연결 | 입력에는 원본 ID를, 완료 결과에는 생성·갱신된 문서/Version ID 목록과 wiki_version_id를 연결한다. |
| JOB-010 | Agent Job Idempotency | 동일 클리핑 요청이 Worker Job을 중복 생성하지 않도록 한다. |
| WC-001 | Queue Job Consume | Worker가 실행 가능한 Personal Wiki Job Batch를 가져온다. |
| WC-002 | Job Claim | FOR UPDATE SKIP LOCKED와 Lease로 Job Batch를 점유한다. |
| WC-006 | Retry 정책 | 재시도 가능한 Chunking·Embedding 실패를 Backoff 후 다시 처리한다. |
| WC-009 | Idempotency 처리 | 같은 원본을 다시 처리해도 document_kind+document_key, Wiki·출처·관계·Snapshot Row가 중복되지 않게 한다. |
| WC-013 | Concurrency 제어 | Claim 크기와 Embedding 동시 실행 수를 별도로 제한한다. |
| DB-004 | 개인 Wiki Chunk 저장 | wiki_chunks에 문서 Version별 Chunk를 영속 저장한다. |
| DB-005 | 개인 Wiki Embedding 저장 | wiki_embeddings에 Chunk별 Vector를 영속 저장한다. |
| DB-026 | Agent Job 저장 | agent_jobs와 agent_job_attempts에 Claim, Lease, 상태와 시도 이력을 저장한다. |

### 웹 클리핑 Worker 완료 계약

- Extension은 service-api의 사용자 인증 경계를 거치고, service-api가 Agent API의 내부 클리핑 경로를 호출합니다.
- Agent API는 source_event_id 멱등성을 확인한 뒤 Source Event, 사용자 원본 문서·Version, Personal Wiki Build Job을 한 Transaction으로 저장합니다.
- Markdown 원문 저장은 LLM 호출 없이 수행하며 title과 본문은 각각 user_source_document_versions.title, raw_content에 보존합니다.
- Worker는 Job Batch를 Lease와 함께 Claim하고 source_document_version_id를 기준으로 Entity·Concept·Schema를 Upsert합니다. 새 문서 Version, 원본·문서 관계, Wiki Build 구성을 한 결과 Transaction에 저장한 뒤 Chunk, Embedding과 관심사를 갱신합니다.
- Worker 재시도 중에도 Markdown 원문과 Frontmatter는 삭제하지 않습니다. 생성 Wiki·출처 관계·Chunk·Embedding만 멱등하게 다시 생성할 수 있습니다.
- 성공 시 Source Event와 Job을 completed로 바꾸고 source_document_id, source_document_version_id, wiki_version_id, affected_documents, chunk_count를 결과에 기록합니다. affected_documents의 각 항목은 document_id, document_version_id, document_kind, document_key, file_path를 포함합니다.
- 최종 실패 시 Source Event와 Job의 오류를 기록하되 저장된 Markdown 원문은 사용자가 삭제할 때까지 유지합니다.

### MVP Batch 처리 계약

- 콘텐츠 생성 트리거는 service 계층 스케줄러가 담당한다(2026-07-20 결정). 사용자 지정 생성 시간의 원천 데이터가 service-db에 있으므로, service 스케줄러가 `schedule window + user_id + content_type` 규칙의 `idempotency_key`로 `POST /generations`를 호출하고, 미리 등록할 때는 `scheduled_at`으로 실행 시각을 예약한다. Agent는 별도의 생성 Scheduler를 두지 않는다(구 SCH-011 제거).
- Agent Worker는 한 트랜잭션에서 실행 가능한 Job 여러 건을 `FOR UPDATE SKIP LOCKED`로 Claim하고, DB Transaction 밖에서 제한된 동시성으로 각 Job을 독립 실행한다.
- Batch Claim 크기와 실제 LLM 호출 동시성은 별도 설정으로 관리한다. 한 Batch를 하나의 LLM 요청으로 합치지 않는다.
- 각 Job은 독립적으로 완료·재시도·실패 처리하며, 생성 후보·Publish Snapshot·Outbox Event를 같은 저장 경계에서 기록한다.
- Spring 계층에서는 HTTP 요청을 처리하는 service-api가 아니라 별도 Service Worker/Scheduler가 Agent API의 Publish Snapshot Batch를 Claim한다. 같은 배포 바이너리를 사용하더라도 실행 역할과 분산 Lock을 분리한다.
- Publish Snapshot Batch 응답은 추가 단건 조회 없이 service-db에 반영할 수 있도록 전체 Snapshot Payload를 포함한다.
- Service Worker는 `content_id + version`으로 service-db에 멱등 Upsert한 뒤, 성공과 실패를 항목별로 모아 부분 성공 Batch ACK한다. 전체 Batch를 하나의 service-db Transaction으로 묶지 않는다.
- ACK되지 않은 항목은 Lease 만료 후 다시 Claim할 수 있고, 재시도 가능 실패는 Backoff 후 `ready`로 돌아가며 최종 실패는 `failed`로 격리한다.
- `CONTENT_READY` 이벤트는 Batch Poll을 즉시 깨우는 신호로 사용하고, 주기적인 Batch Poll을 이벤트 유실과 Backfill의 복구 경로로 유지한다.
- 기존 단건 Snapshot 조회·ACK는 관리자 수동 복구, 장애 조사와 개별 재발행을 위해 유지한다.

## MVP 제외 범위

- 내부 호출 주체별 별도 Secret·세부 Scope 권한·요청 서명
- External Agent API의 생성·번역·추천 기능
- MCP Server의 생성·수집 도구와 OAuth 인증
- 번역 및 이미지 생성
- 별도의 추천 Agent
- 고급 관심사 Graph
- Personal Wiki 전체 재구성 및 Memory 압축
- 다중 평가 Agent와 고급 사실 검증
- Prompt 및 추천 A/B Test
- 고급 메시징 패턴과 자동 확장

## ID 관리 원칙

- 기능 ID는 전체 기능 명세에서만 생성한다.
- MVP 문서는 전체 기능 ID 중 구현 대상을 선별해 참조한다.
- MVP 이후 기능을 구현할 때도 기존 기능 ID를 그대로 사용한다.
- 여러 기능을 개발 작업으로 묶을 때만 별도의 Epic 또는 Milestone ID를 사용한다.
