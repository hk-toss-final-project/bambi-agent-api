<!--
이 문서는 service-api(Spring) ↔ agent-api(FastAPI) 연동 계약 "초안(제안서)"이다.
작성: 소라(연동 담당).
근거: (1) 송우 연동 가이드 docs/service-integration-guide.md (2026-07-20)
      (2) 소라 로컬 E2E 검증 (2026-07-22) — 실제 계약 흐름을 서버에서 직접 밟아 확인.
목적: 우석·소라·송우 "agent 계약 경계 확정" 미팅의 입력물 + 소라 Gateway 구현 설계서.
-->

# Agent 연동 계약 & Gateway 설계

> 상태: **v3 — 결정 1 확정 (2026-07-27).** §5.1의 (B) vs (C)는 **(C) 비동기 전환으로 팀 확정**됐다
> (우석 확인, 07-27). 이 문서에서 "동의 대기"로 남아 있던 표기를 정리했다 — **이 문서를 읽고
> "결정 1이 아직 열려 있다"고 판단하지 말 것.**
>
> (이전) DRAFT v2 — 2026-07-22 로컬 E2E 검증 반영. 초안 v1(07-10 코드 기준)이 전제했던
> "Worker 없음 · 인메모리 · 즉시 카드(동기)"는 검증 결과 모두 바뀌었다(§2.4). 그에 맞춰
> 방향(§3)·컨텍스트 설계(§4)·Gateway 설계(§5)를 다시 썼다.
>
> 소유 경계: **agent-api 코어(엔드포인트·스키마·생성 로직) = 송우/LLM팀**, **연동(Gateway·계약·AI 로그) = 소라**, **창구 = 우석**.

---

## 1. 범위와 아키텍처 원칙

- service-api(Spring, 영현/우석)가 agent-api(FastAPI, 송우)를 **어떤 규약으로 호출하는지**.
- 그 사이 다리인 **AgentGateway(소라, Spring 쪽)**의 호출·변환·에러·타임아웃 규약.
- **AI 로그**를 무엇으로/어디에 남기고 관리자 화면(admin-web, 소라)이 무엇을 읽는지.
- **호출 방향은 service → agent 단방향**(송우 가이드 §1). agent-api는 service를 절대 호출하지 않는다.
  완성 콘텐츠도 **service-worker가 폴링으로 당겨가는 Pull 방식**이다. → service 쪽에 "agent가 부를 수신 엔드포인트"는 필요 없다.
- agent-api·db는 **내부 전용**, 프론트의 agent 직접 호출 금지. 따라서 **agent-api를 부르는 주체는 항상 Spring**이다.

이 문서는 agent-api 내부 구현을 규정하지 않는다(송우 소유). 규정하는 것은 **경계(계약)와 Spring 쪽 Gateway 설계**다.

---

## 2. 지금 실제로 있는 것 (2026-07-22 검증)

### 2.1 경로·헤더 규약
- 내부 API Prefix: **`/internal/v1`** (`API_PREFIX`로 변경 가능).
- 시스템 엔드포인트는 prefix 없이 `/system/*`.
- 추적 헤더: `X-Request-ID`, `X-Trace-ID` (없으면 agent가 생성). **Gateway가 전파한다.**
- 내부 인증: 현재 없음(내부망 전제). 배포 전 협의(§7).

### 2.2 Service → agent 연동 엔드포인트 (전부 비동기 Job)
| Method | Path | 성공 | 용도 |
|---|---|---:|---|
| PUT | `/users/{id}/context` | 200 | 사용자 컨텍스트 upsert. 버전 역행 시 409 `STALE_CONTEXT_VERSION` |
| POST | `/users/{id}/wiki-sources/clippings` | 202 | 웹 클리핑 → Job 등록 |
| POST | `/users/{id}/wiki-sources/urls` | 202 | URL 저장 → Job 등록 |
| POST | `/users/{id}/generations` | 202 | 콘텐츠 생성(Report Builder) → Job 등록 |
| GET | `/jobs/{job_id}` | 200 | Job 상태·진행률 |
| GET | `/jobs/{job_id}/result` | 200 | 완료 결과 (미완료면 409 `JOB_RESULT_NOT_READY`) |
| POST | `/publish-snapshot-batches/claim` | 200 | **(service-worker) 완성 카드 Pull.** `lease_seconds≥30` |
| POST | `/publish-snapshot-batches/{id}/ack` | 200 | (service-worker) 처리 완료 ACK |

`202 Accepted` 응답(`AcceptedJobResponse`):
```json
{ "job_id":"…", "feature_id":"SVC-008", "status":"queued", "request_id":"…",
  "created_at":"…", "generation_request_id":"…" }
```

> 위키마킹(`content-marks`)은 Handler 미구현으로 현재 `501`. 연동 보류(송우 가이드 §3.7).

### 2.3 응답·에러 포맷 (agent 현재 방식)
- **성공**: `{success,data,error}` 래핑 없이 Pydantic 모델을 그대로 반환.
- **에러**: 공통 `{ "code","message","request_id","retryable","details":[] }`.
- 검증 실패: `422` `REQUEST_VALIDATION_ERROR`.
- 주요 코드: `REQUEST_VALIDATION_ERROR(422)`, `USER_CONTEXT_REQUIRED(409)`, `STALE_CONTEXT_VERSION(409)`,
  `JOB_NOT_FOUND(404)`, `JOB_RESULT_NOT_READY(409)`, `INVALID_JOB_PAYLOAD`, `PUBLISH_SNAPSHOT_MISMATCH(409)`,
  `PUBLISH_BATCH_LEASE_EXPIRED(409)`, `SERVICE_NOT_READY(503)`, `INTERNAL_SERVER_ERROR(500)`.

> ⚠️ 팀 공통 `{success,data,error}`와 **다르다.** 변환 경계 = Gateway(§5).

### 2.4 검증된 실제 동작 (초안 v1 정정)
초안 v1이 "미구현"이라 적었던 것은 지금 **전부 동작한다.** 07-22 로컬에서 직접 확인:

- ✅ 저장소는 **PostgreSQL 17 + pgvector**(인메모리 아님). 재시작해도 데이터 유지.
- ✅ **Worker 있음** — `bambi-generation`(리포트 생성), `personal-wiki`(위키 빌드) 등. Job이 실제로 `completed` 됨.
- ✅ **E2E 카드 생성 검증** — `PUT context → POST generations(202) → job 실행 → generated-contents` 로
  실제 LLM 카드(title·summary·body·citations) 생성됨. 본문에 `[P1][P2][P3]`(개인 위키) 인라인 인용 확인.
  (외부 문서 `[G1..]`는 계약상 존재하나 이번 실행에선 미발생 — 외부 수집이 결과를 안 준 것으로 보임. 별도 확인 필요.)
- ✅ **service-worker Pull 검증** — seed 발행 Snapshot 3건을 `publish-snapshot-batches/claim`으로 그대로 수신.

**⚠️ 새로 발견한 전제조건 (실패가 2단계로 나뉨):**
1. **컨텍스트 자체가 없으면** → `POST /generations`가 즉시 `409 USER_CONTEXT_REQUIRED`로 거부(송우 가이드 §3.4 기준. 본 검증에선 미실시).
2. **컨텍스트는 있으나 위키·관심사가 없으면** → 요청은 `202`로 접수되지만 **Job 실행 시점에 `INVALID_JOB_PAYLOAD`(retryable:false)로 실패**(직접 확인, OpenAI 호출 전).

즉 파이프라인은 **저장 → 위키 빌드 → 관심사 추출 → 생성** 순서를 전제한다. Gateway/플로우가 이 순서를 지켜야 한다.

> 파이프라인은 "Bambi 생성"에서 **Report Builder**로 리네임됨(마이그레이션 0006). 콘텐츠 유형 예: `article`, `interest_news_card`(기본).

---

## 3. 확정된 방향 (초안 v1 GAP 재정리)

| # | 항목 | v2 상태 |
|---|---|---|
| GAP-1 | agent가 동기냐 비동기냐 | ✅ **해소 — agent는 완전 비동기 + Pull 확정(송우 07-22).** 동기 엔드포인트 안 둠. 초안의 (A) 동기안 폐기. (Spring이 이 비동기를 어떻게 다룰지 = 별도 결정 §5.1·§7) |
| GAP-2 | `{success,data,error}` 변환 경계 | **제안 유지 — Gateway 한 곳에서 변환**(§5.3). 영현(공통 응답) 확인 필요. |
| GAP-3 | 생성 결과 스키마 매핑 | ✅ **확정(송우 07-22, §3.1).** card=요약+관심사태그 / body는 service `report` 테이블에 보존 / why_for_you 문장 폐기→관심사 태그. |
| GAP-4 | 저장 스키마 분담 | 관심사·위키·임베딩 = agent schema(송우). **report(본문 포함)·card·피드·좋아요·AI 로그 = service schema** — service-worker Pull이 report 저장(송우 07-22 "(나)"). 스키마 변경은 영현·우석 확인. |

### 3.1 카드/리포트 스키마 매핑 (agent 결과 → service 저장) — ✅ 확정(07-22)

**확정 구조:** agent 리포트를 service-db에 담을 때 **두 곳**으로 나눈다.
- **`service.report`(신설):** `title` + `summary` + **`body`** + citations. **service-worker가 Pull(claim)로 저장.** service가 본문(리포트)을 소유·관리. (송우 07-22 "(나)")
- **`service.cards`(기존, 유지):** `title` + `summary` + **관심사 태그** + `report_id` 참조. **body 없음**(카드는 요약만). 피드·좋아요·공개는 카드에 그대로.

| agent 결과 | → 저장 위치 | 비고 |
|---|---|---|
| `title` | report.title, card.title | 그대로 |
| `summary` | report.summary, card.summary | 그대로 (카드는 요약만 노출) |
| `body` | **report.body** | 카드엔 안 넣음. 리포트에 보존 |
| `citations[…]` | report(citations) / card_sources | citation 구조는 아래 주의 |
| interests(관심사) | **card 관심사 태그** | why_for_you 문장 대체. ✅ 2026-07-30 연결됨 — 발행 Snapshot payload의 `tags`(생성 요청 topic, 항상 1개)를 service가 `card_interest_tags`에 그대로 저장 |
| ~~why_for_you~~ | (폐기) | "왜 당신에게" 문장 안 씀 → 관심사 태그로 대체 |

> ⚠️ `report`·카드 관심사 태그는 **service DB 스키마 변경** → 영현·우석 소유. 소라+서빈이 스케줄링/Pull 저장 구현.

**citation 구조 주의 (검증):** 생성 카드(`generated-contents`)의 citation은
`{citation_id, ordinal, reference("P1"/"G1"), document_version_id, chunk_id, title, url, quoted_text}` 형태다.
- **개인 위키(P) citation은 `url=null`**(위키엔 외부 URL 없음) → `card_sources.url`이 빈다. 외부(G) citation만 url이 있다.
- P/G 구분(`reference`)은 `card_sources`에 저장 시 소실 → 필요하면 컬럼 추가.
- 참고: **발행 Snapshot(claim) 카드의 citation은 `{citation_id,title,url}`로 더 단순** — 두 citation 모양이 다르다.
- 발행 Snapshot payload는 citation 외에 **`tags`**(카드 관심사 태그)를 함께 싣는다. 상세는 [service-integration-guide.md](service-integration-guide.md) "Claim 응답" 절.
- 참고: 기존 동기 계약의 `BookmarkProcessResponse{summary, interests[], tags[], confidence}` 중 `confidence`·`tags`는 agent 실제 결과에 대응이 불명확 → 관심사 태그로 정리되며 자연 흡수.
- ✅ **결정 완료(07-22, 송우).** 구현 소유: `report`/카드 관심사태그 스키마 = 영현·우석, service-worker Pull 저장·스케줄링 = 소라·서빈.

---

## 4. 컨텍스트 동기화 설계 (`PUT /users/{id}/context`) — 착수 지점

> **왜 최우선인가:** 컨텍스트 없는 사용자의 생성 요청은 `409 USER_CONTEXT_REQUIRED`로 즉시 거부되고,
> 컨텍스트가 있어도 위키·관심사가 없으면 Job이 `INVALID_JOB_PAYLOAD`로 실패한다(§2.4). **가입 플로우에 반드시 포함**해야 이후 agent 기능이 동작한다.

### 4.1 언제 호출하나 (Spring 훅)
1. **회원가입 성공 직후 1회 (필수)** — `context_version=1`로 최초 등록.
2. **설정 변경 시마다** — plan(무료↔유료)·선호 언어·개인화 on/off·차단 관심사/소스 변경.

### 4.2 요청 필드 매핑 (service-db 원천 → agent context)
| agent 필드 | 필수 | service 원천 | 비고 |
|---|---|---|---|
| `context_version` | O | 사용자별 **단조 증가 정수** | service-db가 원천. 아래 §4.3 |
| `plan` | O | `user.plan` | `free` \| `paid` |
| `preferred_language` | X | 사용자 설정 | 기본 `ko` |
| `personalization_enabled` | X | 사용자 설정 | 기본 `true` |
| `blocked_interest_ids` | X | 사용자가 삭제한 관심사 | 송우 확인(07-21): agent가 `agent.user_context_snapshots`(테이블 실재 확인)에 반영. 현재 빈 배열, 삭제 기능 붙으면 채움 |
| `blocked_source_ids` | X | 사용자가 삭제한 소스 | 위와 동일 |

### 4.3 버전 관리 (핵심)
- `context_version`은 **사용자별로 단조 증가**해야 한다. 같거나 작은 값 재전송 → `STALE_CONTEXT_VERSION`.
- **제안:** service-db 사용자 레코드에 `agent_context_version` 컬럼(정수). 가입 시 1, 컨텍스트 변경마다 +1 후 그 값으로 PUT.
- `STALE_CONTEXT_VERSION(409)`은 **오류가 아니라 "이미 최신"** 신호 → Gateway가 삼키고 성공 처리(§5.4).

### 4.4 순서·실패 정책
- **순서 불변식:** 특정 사용자의 `generations` 이전에 그 사용자의 `context`가 반드시 한 번 반영돼 있어야 한다.
- **실패 시(가입 중 agent 다운):** 가입은 사용자向 흐름, agent는 내부 비필수 → **가입 자체를 막지 않는다.**
  사용자를 "agent 미동기(agent_synced=false)"로 표시하고 **재동기(backfill) 큐/재시도**로 나중에 PUT. 재동기 전엔 그 사용자 생성 요청을 보류.
- (검증 완료: `PUT context` → 200 `feature_id:"SVC-001"`, 필드 그대로 echo.)

---

## 5. AgentGateway 설계 (소라, service-api)

### 5.1 기존 Spring 계약과의 충돌 (이 설계의 핵심 결정)
service-api엔 이미 **동기** `AgentClient` 인터페이스가 있다(`com.bambi.service.agent`, 소라가 P1에서 실제 구현으로 교체 예정):
- `processBookmark(req) → {summary, interests[], tags[], confidence}` — 즉시 반환
- `generateCards(req) → {cards[{title,summary,whyForYou,sources[]}]}` — 즉시 반환

인터페이스 주석: *"이 인터페이스(=계약)만 지키면 도메인 코드는 안 건드림."* 즉 **영현/우석 의도 = 동기 유지, 속만 FastAPI로.**
그런데 agent-api는 **비동기 202+Pull**(§3). 두 방식이 충돌한다. → **택1 필요:**

- **(B) 동기 shim** — `AgentClient` 인터페이스 유지. Gateway가 내부에서 `generations(202)` 등록 후 `jobs/{id}/result`를 **블로킹 폴링**해 카드까지 만들어 동기 반환. 도메인 코드 무변경. 단 (1) 저장 요청이 LLM 수십 초를 대기 (2) service-worker Pull 경로와 이중화.
- **(C) 비동기 전환** — 저장은 즉시 "생성 중" 반환, 생성은 트리거만, **카드는 service-worker claim이 나중에 적재 → 피드 갱신**. agent 실제 설계와 정합. 단 `AgentClient` 인터페이스·저장→카드→피드 흐름 변경(영현 협의) 필요.
- **소라 관점:** 장기적으론 (C)가 정합(Pull이 이미 구현됨). P0 데모가 "즉시 카드"를 요구하면 (B)로 시작해 (C)로 이행하는 절충도 가능. **결정 주체: 소라·영현·우석·송우.**

> ✅ **확정 (2026-07-27): (C) 비동기 전환.** 저장은 즉시 반환, 생성은 별도 트리거(정기 브리핑/온디맨드),
> 카드는 service-worker claim으로 적재. 기존 동기 "즉시 카드" 경로는 제거하지 않고
> **플래그(`app.agent.immediate-card.enabled`)로 격리** — 비동기 경로가 배포 환경에서 실제 카드를
> 적재하는 것을 확인한 뒤 OFF 한다(데모 안전장치).

> 또한 **동기 메서드 1개 = agent 다단계 파이프라인**이다. `processBookmark` → (클리핑 저장 → 위키 빌드 → 관심사 추출) 여러 Job, `generateCards` → (generations → 완성 대기). 1:1 아님 — Gateway가 이 다단계를 조립해야 한다.

### 5.1b 성격 — (C) 기준: "비동기 어댑터", 카드를 기다리지 않는다
아래 흐름도는 **(C) 비동기 전환**을 택한 경우다. Gateway는 **호출을 던지고 즉시 반환**하고, 카드는
나중에 **service-worker의 claim 루프**가 service-db로 당겨온다. Gateway의 일은 **호출·헤더 전파·응답 변환·AI 로그**까지다.

```
[가입]        UserService ──▶ AgentGateway.putContext()           ──▶ PUT  /context      (200)
[저장]        SourceService ─▶ AgentGateway.ingestClipping()/Url() ──▶ POST /wiki-sources (202 job_id)
[생성 트리거] Scheduler ──────▶ AgentGateway.requestGeneration()   ──▶ POST /generations   (202 job_id)
[수신(별도)]  service-worker ─▶ (publish-snapshot-batches claim/ack 폴링 루프) ──▶ service-db 저장 → 피드/관리자
```
> 저장/생성 응답은 202+job_id일 뿐 "카드"가 아니다. Gateway 호출자는 job_id만 받고 흐름을 계속한다.

### 5.2 위치·구성 (제안)
- 패키지 `…​.agent` — 인터페이스 `AgentGateway` + 구현 `AgentGatewayClient`(Spring `RestClient`/`WebClient`).
- 설정: `AGENT_API_BASE`(내부 주소), 타임아웃, 재시도.
- 호출자: `UserService`(컨텍스트), `SourceService`(저장), 생성 `Scheduler`. **HTTP 세부는 Gateway 안에만.**

### 5.3 응답·에러 변환 경계 (GAP-2)
- **원칙: 변환은 Gateway 한 곳.** agent `{code,message,retryable,…}`를 받아
  - 성공 → 도메인 결과(예: `AgentJobRef{jobId,status}`) 반환. 바깥 컨트롤러는 기존 팀 공통 `{success,data,error}` advice로 감싼다.
  - 실패 → agent code를 **팀 코드로 매핑한 도메인 예외**로 던짐. 전역 예외 핸들러가 `{success:false,error:{code,message}}`로 변환.
- **에러코드 매핑(제안):**
  | agent | HTTP | Gateway 처리 | 팀 코드 |
  |---|---:|---|---|
  | `INTERNAL_SERVER_ERROR`/5xx/타임아웃 | 5xx | 재시도 후 실패 | `AGENT_UNAVAILABLE`(retryable) |
  | `SERVICE_NOT_READY` | 503 | Backoff 재시도 | `AGENT_UNAVAILABLE` |
  | `STALE_CONTEXT_VERSION` | 409 | **성공 처리(삼킴)** — 이미 최신 | — |
  | `USER_CONTEXT_REQUIRED` | 409 | 컨텍스트 먼저 PUT 후 재시도 | 내부 정합성 로그 |
  | `REQUEST_VALIDATION_ERROR`/`INVALID_JOB_PAYLOAD` | 422/– | 우리 요청 결함 → 로그 | `AGENT_BAD_REQUEST` |
  | `JOB_RESULT_NOT_READY` | 409 | 비동기 정상 — 나중에 polling/claim | — |

### 5.4 타임아웃·재시도
- 호출은 202 반환용 가벼운 요청 → 타임아웃 **제안 3s**(연결 실패·5xx만 걸림). LLM 대기 아님.
- `retryable:true`(5xx/503) → 짧은 Backoff 재시도(최대 2회). 그 외 즉시 실패.
- **가입/저장은 agent 장애로 막지 않는다** — 실패해도 사용자 흐름은 성공시키고, agent 반영은 재시도 큐로(§4.4).

### 5.5 AI 로그 연결점
- Gateway는 각 호출 **전후를 감싸 AI 로그 1건**을 남기기 좋은 지점(§6). 호출 성공/실패·소요시간·요청ID·에러코드를 여기서 기록.

---

## 6. AI 로그 계약 (소라)

테이블은 **이미 V1에 존재**한다(신설 아님). `MockAgentClient` 주석도 *"DB AI 로그(`ai_request_logs`/`ai_response_logs`) 적재는 실제 Gateway(P1, 소라)가 붙인다"*고 못박음. 즉 이 적재 코드가 소라 Gateway의 일이다.

- **`service.ai_request_logs`** (요청): `user_id`, `endpoint`(예: `/agent/bookmarks/process` 또는 실제 agent 경로), `request_body`(JSONB), `created_at`.
- **`service.ai_response_logs`** (응답): `request_id`(FK), `status_code`, `response_body`(JSONB), `latency_ms`, `created_at`.
- **누가·언제:** Gateway가 agent 호출 **직전 request 로그 1건 → 응답/실패 시 response 로그 1건**(같은 request_id) 기록(§5.5). latency_ms·status_code는 여기서 자연스럽게 나옴.
- **비동기 주의:** (C) 전환 시 "요청 시점"과 "카드 완성 시점(service-worker claim)"이 분리된다. 요청/즉시응답은 위 두 테이블로, **완성 결과는 claim 처리 시점에 별도 기록**하고 **`job_id`(또는 request_body 내 식별자)로 연결**한다. → 완성 로그를 어느 테이블에 남길지(응답 로그 확장 vs 별도)는 영현과 확정(§7).
- **관리자 API(소라, 구현·머지 완료):** `GET /api/admin/ai-logs`(ADMIN, 페이지네이션, 팀 공통 응답). admin-web이 소비. **단 현재 적재 코드가 없어 목록은 빈 상태가 정상** — Gateway 적재가 붙어야 채워진다.

---

## 7. 남은 확정 사항 → 다음 액션

| # | 질문 | 결정 주체 | 상태 |
|---|---|---|---|
| **동기 vs 비동기 전환** | (B) vs (C) — §5.1 | 소라·영현·우석·송우 | ✅ **확정(07-27): (C) 비동기 전환.** 기존 즉시 카드는 플래그 격리 후 검증 뒤 OFF |
| GAP-3 | 카드/리포트 매핑(§3.1) | 송우·영현·소라 | ✅ **확정(07-22): card=요약+관심사태그 / body=service report 보존 / why_for_you 폐기** |
| GAP-4 | 저장 스키마 분담 | 송우·영현 | 🔶 방향 확정(service가 report 소유·Pull 저장). `report` 테이블·카드 태그 스키마 변경은 영현·우석 확인 |
| 순서 전제 | 생성 전 위키/관심사 필요 — 저장→생성 트리거(스케줄러) 시점 | 소라·서빈·송우 | ⬜ (service-api swagger 스케줄링 계약 확인) |
| 컨텍스트 | `agent_context_version` 컬럼·재동기 큐 도입 | 소라·영현 | ⬜ |
| 변환 경계 | Gateway = `{success,data,error}` 변환 지점 확정 | 소라·영현 | ⬜ |
| 내부 인증 | 무인증 → 공유 시크릿 vs 네트워크 격리 | 전원 | ⬜(배포 전) |
| 차단 ID | `blocked_*_ids` 실제 연결(삭제 기능) | 소라·송우 | ⬜(개인화 고도화) |

**다음 스텝 (07-27 갱신):** ~~결정 1(B/C) 동의~~ ✅ (C) 확정 → ① `reports` 테이블(본문 보존, GAP-3/4 이행) V4 마이그레이션(영현) ② 클리핑·조회 API 중계 + claim/ack HTTP 클라이언트(소라) ③ 생성 트리거 스케줄러 — service 책임(송우 가이드 §3.4, 담당 확정 필요) ④ 컨텍스트 동기화는 구현 완료(단 `agent_context_version` 컬럼 없어 재동기 불가 — 별도).
