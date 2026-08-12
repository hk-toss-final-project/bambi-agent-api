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
- 내부 인증: `/internal/v1/**` 요청은 Agent 전용 opaque Bearer 토큰을 사용한다.
  Service와 Agent에 같은 `AGENT_INTERNAL_TOKEN` Secret을 주입하며 사용자 JWT는
  전달하거나 재사용하지 않는다.

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
| `cover_image` | **report 대표 이미지** | 실제 인용 출처를 순회해 IMG-013이 고른 HTTPS 이미지+원문 출처. 없으면 null |
| interests(관심사) | **card 관심사 태그** | why_for_you 문장 대체. ✅ 2026-07-30 연결됨 — 발행 Snapshot payload의 `tags`(생성 요청 topic, 항상 1개)를 service가 `card_interest_tags`에 그대로 저장 |
| ~~why_for_you~~ | (폐기) | "왜 당신에게" 문장 안 씀 → 관심사 태그로 대체 |

> ⚠️ `report`·카드 관심사 태그는 **service DB 스키마 변경** → 영현·우석 소유. 소라+서빈이 스케줄링/Pull 저장 구현.

**citation 구조 주의 (검증):** 생성 카드(`generated-contents`)의 citation은
`{citation_id, ordinal, reference("P1"/"G1"/"L1"), document_version_id, chunk_id, global_source_document_id, title, url, quoted_text}` 형태다.

#### 출처 종류는 셋이다 (2026-08-04 실측 확인)

`reference` 접두 문자로 구분하며, **채워지는 컬럼 조합이 종류마다 다르다.**

| 종류 | 무엇 | `document_version_id` | `global_source_document_id` | `url` |
|---|---|---|---|---|
| `P` | 개인 Wiki 문서 | ✅ Wiki 문서 UUID | ✖ | ✖ (위키엔 외부 URL 없음) |
| `G` | Global 풀(수집 캐시) 문서 | ✖ | ✅ 캐시 문서 UUID | ✅ 기사 주소 |
| `L` | 실시간 수집 자료 | ✖ | ✖ | ✅ 기사 주소만 |

```
[P7] 시가총액 방식              document_version_id=0ae18143-…  url=null
[G1] 환율 월평균 39.1원 …        global_source_document_id=33932b1c-…  url=https://view.asiae.co.kr/…
[L1] DDD: I wrote a free …      둘 다 null                     url=https://www.reddit.com/…
```

**`G`와 `L`의 차이가 화면 설계에 영향을 준다.** 둘 다 외부 기사이고 `url`이 있지만,
`G`는 본문이 우리 DB(`global_source_documents.markdown`)에 보존돼 있어 원문이 바뀌거나
사라져도 근거를 확인할 수 있다. `L`은 URL이 유일한 증빙이다. 같게 취급하면 `G`의
이 장점이 화면에서 사라진다.

- P/G/L 구분(`reference`)은 `card_sources`에 저장 시 소실 → 필요하면 컬럼 추가.
- ⚠️ **2026-07-28 이전에 생성된 `G` citation 4건은 `global_source_document_id`가 비어 있다.**
  Migration 0008(캐시 테이블 분리) 적용 전에 만들어진 것이라 소급되지 않는다.
  이후 생성분은 정상이며, 과거 데이터를 다루는 쪽은 null 가능성을 전제해야 한다.
- 참고: **발행 Snapshot(claim) 카드의 citation은 `{citation_id,title,url}`로 더 단순** — 두 citation 모양이 다르다.
- 발행 Snapshot payload는 citation 외에 **`tags`**(카드 관심사 태그)를 함께 싣는다. 상세는 [service-integration-guide.md](service-integration-guide.md) "Claim 응답" 절.
- 발행 Snapshot은 요청에서 받은 값 **두 개를 해석 없이 되돌려준다** — `report_type`(생성 맥락)과
  `request_idempotency_key`(어느 요청의 결과인가). 둘 다 2026-08-06에 함께 합의됐으나
  **이 문서에 `report_type`만 적혀 있어서 `request_idempotency_key`가 구현에서 누락됐고**,
  그 사이 service는 `generation_pendings`를 완료로 전환하지 못했다(2026-08-10 채움).
  ⚠️ 합의한 필드는 코드보다 **이 문서에 먼저** 적는다 — 에이전트·팀 모두 문서를 보고 구현한다.
- 참고: 기존 동기 계약의 `BookmarkProcessResponse{summary, interests[], tags[], confidence}` 중 `confidence`·`tags`는 agent 실제 결과에 대응이 불명확 → 관심사 태그로 정리되며 자연 흡수.
- ✅ **결정 완료(07-22, 송우).** 구현 소유: `report`/카드 관심사태그 스키마 = 영현·우석, service-worker Pull 저장·스케줄링 = 소라·서빈.

---

## 4. 컨텍스트 동기화 설계 (`PUT /users/{id}/context`) — 착수 지점

> **왜 최우선인가:** 컨텍스트 없는 사용자의 생성 요청은 `409 USER_CONTEXT_REQUIRED`로 즉시 거부되고,
> 컨텍스트가 있어도 위키·관심사가 없으면 Job이 `INVALID_JOB_PAYLOAD`로 실패한다(§2.4). **가입 플로우에 반드시 포함**해야 이후 agent 기능이 동작한다.

### 4.1 언제 호출하나 (Spring 훅)
1. **회원가입 성공 직후 1회 (필수)** — `context_version=1`로 최초 등록.
2. **설정 변경 시마다** — 온보딩 Category·Topic 선택, plan(무료↔유료)·선호 언어·개인화 on/off·차단 관심사/소스 변경.

### 4.2 요청 필드 매핑 (service-db 원천 → agent context)
| agent 필드 | 필수 | service 원천 | 비고 |
|---|---|---|---|
| `context_version` | O | 사용자별 **단조 증가 정수** | service-db가 원천. 아래 §4.3 |
| `plan` | O | `user.plan` | `free` \| `paid` |
| `preferred_language` | X | 사용자 설정 | 기본 `ko` |
| `personalization_enabled` | X | 사용자 설정 | 기본 `true` |
| `interest_taxonomy_version` | X | 온보딩 선택 | Category·Topic 안정 ID를 해석할 분류체계 버전 |
| `selected_category_ids` | X | 온보딩 선택 | 선택한 Category 안정 ID 목록(최대 8개) |
| `selected_topic_ids` | X | 온보딩 선택 | 선택한 Topic 안정 ID 목록(최대 12개) |
| `blocked_interest_ids` | X | 사용자가 삭제한 관심사 | 송우 확인(07-21): agent가 `agent.user_context_snapshots`(테이블 실재 확인)에 반영. 현재 빈 배열, 삭제 기능 붙으면 채움 |
| `blocked_source_ids` | X | 사용자가 삭제한 소스 | 위와 동일 |
| `signup_interests` | X | 가입 시 고른 관심 카테고리·토픽 | `[{"category","topics":[...]}]`. agent가 `user_context_snapshots.attributes.signup_interests`에 버전과 함께 보존(재계산에 안 지워짐). **있으면 agent가 온보딩 시드(WSE-014)를 자동 접수해 콜드스타트 관심사를 파생** — 아래 참고 |
| `onboarding_reports_managed_by_service` | X | Service 온보딩 완료 처리 | 기본 `false`. `true`이면 Agent의 가입 관심사별 자동 리포트 등록을 생략하고 Service가 SVC-008 호출과 펜딩 상태를 소유 |

### 4.2-1 온보딩 관심사 시드 + 웰컴 리포트 (콜드스타트)
- **시드 (WSE-014, agent 자동):** `signup_interests`가 있으면 context 수신 시 agent가 선택을 시드 Markdown으로 합성해 사용자별 단일 활성 `onboarding_seed` Head의 Version·Personal Wiki Build Job으로 **자동 접수**한다. `selected_topic_ids`는 Agent DB에 미리 관리한 결정론적 정의·특징·활용을 사용하고 정식 복합 명칭을 분해하지 않는다. `category=null` 그룹의 Topic은 사용자 추가 키워드이며 taxonomy 별칭→기존 Wiki→사용자 서명 캐시→LLM 일반론→결정론 폴백 순으로 해석한다. 같은 선택은 현재 Version을 재사용하고 변경된 선택은 다음 Version+Full Rebuild로 이전 시드 전용 노드를 제거한다. 빌드 완료 후 INT-011 훅이 관심사 프로필을 파생시킨다. 컨텍스트 저장과 분리된 best-effort이고 Service의 추가 호출은 불필요하다.
- **온보딩 리포트 (Service 소유):** Service는 컨텍스트에
  `onboarding_reports_managed_by_service=true`를 보내 Agent의 레거시 자동 등록을
  끈 뒤, 선정한 실제 관심사로 SVC-008을 최대 3회 호출한다. 구버전 Service 호환을
  위해 필드 생략 시에는 기존 Agent 자동 등록을 유지한다.
- **⚠️ `topic` 은 표시용 라벨이 아니라 agent 의 실제 검색어다 (2026-08-05 확인, 실사고 있었음).**
  Service 가 `"오늘의 관심사 뉴스"` 같은 **고정 문구**를 넣었더니 agent 가 그 문구로 검색해
  관심사와 무관한 기사를 물어왔다. 지금은 **사용자의 실제 관심 주제 문자열**(예: `"SK하이닉스"`)을 넣는다.
  화면에 보여줄 문구가 필요하면 Service 응답에서 따로 만들고, 이 필드에는 넣지 않는다.
- **`report_type` (요청 → Snapshot 그대로 반환, 2026-08-06 이송우 협의):**
  `POST /generations`에 `report_type`(선택, 기본 `""`)을 실으면, agent가 해석하지 않고
  발행 Snapshot의 `report_type`에 **받은 문자열 그대로** 담아 Claim 시점에 돌려준다.
  요청과 Claim 시점이 떨어져 있어 Service가 카드의 생성 맥락을 다시 짜맞추지 않게 하려는 값이다.
  - 값의 정의·검증은 **Service가 소유**한다. agent는 목록을 두지 않고 저장·반환만 한다(길이 64자 제한).
  - **현재 쓰는 값 3개** (2026-08-06 확정, 값 추가 시 Service가 공지):

    | 값 | 트리거 | 누가 보내나 |
    |---|---|---|
    | `MORNING_BRIEFING` | 매일 아침 스케줄러 | Service |
    | `ON_DEMAND` | 사용자가 "지금 생성" | Service |
    | `ONBOARDING` | 온보딩 관심사 저장 직후 첫 리포트 | **agent 자신** (아래 참고) |

  - `content_type`과 다른 축이다. `content_type`=콘텐츠 종류(기본 `interest_news_card`), `report_type`=생성 맥락.
  - 생략하면 `""`. 이전에 저장된 Snapshot도 `""`로 읽힌다.
- **⭐ 아침 브리핑만 `topics[]`, 온디맨드는 단일 주제 (2026-08-10 확정)**

  | 경로 | 주제 | 고르는 주체 | 보내는 것 | agent 경로 |
  |---|---|---|---|---|
  | 아침 브리핑 | 최대 3개 | **시스템** (개인 LLM Wiki 맥락에서 선정) | 준비 완료 시 `topic="오늘의 관심사 브리핑"` + `topics=[선정 이름]`; 미준비 즉시는 `WIKI_BRIEFING` | 여러 주제 |
  | 온디맨드 | **1개** | **사용자** (화면에서 즉석 선택) | `topic="고른 주제"`, `topics` 없음 | 단일 주제 |

  Service 는 주제의 **이름**을 `topics` 에 담는다. UUID 가 아니다. 이름은 아래
  **아침 브리핑 Wiki 전용 주제 결정** 항목이 정한다. 08-10까지 쓰던
  `GET /internal/v1/users/{id}/interests`와 Service 등록 관심사는 이 경로에서 사용하지 않는다.

  ⚠️ **08-07 저녁 계약(둘 다 topics[] 3개, 온디맨드는 topTags(3) 자동)은 폐기됐다.**
  자동 선정이 아래 두 문제를 안고 있어 **사용자가 결과를 즉시 보는 온디맨드에서 뺐다.**

  - **파편이 상위에 온다.** 실측: `DBeaver Community`·`OpenWiki`·`pgAdmin 4`(도구),
    `기술노트with 알렉`(출처)이 관심사 상위권이었다. 08-08에 이를 걸러내는 필터를 넣었다가
    삼성전자·SK하이닉스·마이크론까지 함께 사라져 08-10에 걷어냈다(agent 쪽 순위 과제로 남음).
  - **순위가 흔들린다.** 점수에 "이걸 뉴스로 받고 싶은가"가 없어서, 글 하나만 더 저장해도
    상위 3개가 뒤바뀐다.

  온디맨드는 사용자가 직접 고르므로 두 문제가 모두 사라지고, 단일 주제 경로라 근거도 두껍다
  (12건 · 상대 점수 컷 · Wiki 이웃 확장 전부 적용). 온디맨드 주제 선택 UI(service-web #55)를
  그대로 쓴다 — 08-07 저녁에 "멈춰 달라"고 요청했던 것을 되돌린다.

  🚨 **다만 그 두 문제는 사라진 게 아니라 아침으로 옮겨갔다 (2026-08-10 아침 자동 선정 결정).**
  아침은 사용자가 결과를 검토하지 않고 그냥 받는 경로라, 파편이 뽑히면 그대로 발행된다.
  실측된 상위 관심사가 `기술노트with 알렉`(블로그 이름)·`AI 시대 개발을 위한 필수 IT 지식`
  (책 제목)인 사용자가 있다. **관심사 순위 개선이 아침 품질을 직접 좌우하게 됐다** —
  agent 쪽 과제로 남는다(명단에서 빼지 않고 순위로 다루는 방향).

  → 08-11 에 그 대응으로 **점수 상위 N개 대신 맥락을 읽어 고르는 엔드포인트**가 들어왔고,
  08-12에 Service 등록 관심사 폴백을 제거해 이 경로를 아침 생성의 유일한 주제 원천으로 확정했다.
  아침 자동 발행의 민감 주제 제외 규칙도 이 선정 단계에 적용한다.

  아래 `topics` 규칙은 **아침 브리핑에만** 해당한다.

  - **⚠️ `topics`를 채우면 `topic` 의 의미가 바뀐다.** 평소 `topic` 은 agent 의 **실제 검색어**지만
    (2026-08-05 항목 참고), `topics` 가 있으면 `topic` 은 **카드 제목·`generation_topic` 표시용**이 되고
    본문이 다루는 주제는 `topics` 목록이 결정한다. 두 규칙이 정반대라 헷갈리기 쉬우니 여기 못 박는다.
    그래서 고정 문구를 `topic` 에 넣어도 된다 — 그 문구로 검색하지 않는다.
  - **🚨 준비 완료 상태에서 `topics` 가 비면 Service 는 요청 자체를 보내지 않는다.** `topic` 만 남는
    순간 그 고정 문구가 실제 검색어가 되기 때문이다. 단, Snapshot 미준비 상태는 빈 완료와 구분해
    `generation_scope=WIKI_BRIEFING` Job이 개인 Wiki 준비 후 실제 topics를 채울 수 있다.
  - **⭐ 아침 브리핑 Wiki 전용 주제 결정 (2026-08-12 개정 — 등록 관심사 폴백 없음)**

    **아침 주제는 사용자가 고르지 않으며 Service 등록 관심사도 읽지 않는다.** 다음 순서로 처리한다.

    1. Service Scheduler가 생성일 전 준비 시각에
       **`POST /internal/v1/users/{user_id}/briefing-preparations`**로 날짜별 비동기 Job을
       멱등 등록한다. Agent는 개인 Wiki 맥락으로 주제를 고르고 Wiki·Global·Live 근거를
       Snapshot으로 고정한다.
    2. 생성 시각에는
       **`GET /internal/v1/users/{user_id}/briefing-topics?briefing_date=YYYY-MM-DD&limit=3`**로
       준비된 주제만 DB에서 읽는다. 응답의 `preparation_status`는 `READY` 또는
       `NOT_PREPARED`다. READY이면 같은 `topics[]`와 `briefing_date`를 생성 요청에 넣고,
       READY인데 topics가 비면 정상적으로 건너뛴다.
    3. 정기 생성에서 NOT_PREPARED이면 Outbox가 재시도한다. 즉시 생성은
       `WIKI_BRIEFING` Job을 접수하고, Report Worker가 REPORT-022와 같은 사용자·날짜 잠금으로
       주제 선정·근거 예열을 마친 뒤 생성을 이어간다.

    - 주제별 Wiki 읽기는 **1홉, 최대 6페이지·12청크**다. 아침은 서로 다른 관심사 최대 3개를
      다루므로 2홉으로 넓히지 않는다.

    - ⚠️ **08-11 낮에 "사용자 선택을 1단계로 앞에 둔다"는 안이 잠깐 확정됐다가 같은 날
      철회됐다.** 최종은 위 2단이고 **선택 화면은 없앤다**(service-web #74). 그 사이에 오간
      "#59 를 살린다"는 결정은 **이 항목으로 대체된다** — 옛 메시지를 보고 3단으로 구현하지 않도록
      여기 못 박는다.
    - 📌 **그래서 `service.user_briefing_topics` 와 `GET`·`PUT /api/users/me/briefing-topics`
      는 호출부가 없어진다.** 코드프리즈 중이라 지우지 않고 남긴다. 지울지 여부는 제출 후
      결정한다 — 되살릴 가능성이 있는 쪽이라 급히 없앨 이유가 없다.
    - **1단계는 관심사 점수 상위 N개가 아니다.** 연결 수 상위를 그대로 쓰면 도구·출처가 주제가
      되므로(실측 `DBeaver Community` 1.00), 후보를 넓게 받아 맥락을 읽고 고른다. 응답은
      `{preparation_status, topics, reason, candidate_count}` 이고 `reason` 은 로그·디버깅용이라
      사용자에게 안 보인다.
    - 08-08에 넣었던 파편 필터(도구·출처로만 등장한 노드를 관심 후보에서 제외)는 **08-10에
      걷어냈다** — 도구와 함께 삼성전자·SK하이닉스·마이크론까지 사라졌기 때문이다. 지금은
      판정만 기록하고 후보에서는 빼지 않는다. **그래서 위키 태그는 계속 오염된 채로 오고**,
      1단계가 맥락을 읽어 고르는 방식인 것이 그 대응이다.

  - **🚨 민감 주제는 아침 자동 발행에서 제외한다 (2026-08-11 우석 확정)**

    | 범주 | 예 |
    |---|---|
    | 자살·자해 | 자살 예방, 자해 |
    | 재난 사망 | 사망자가 나온 사고·재난 |
    | 정치인 실명 | 특정 정치인 이름이 주제가 된 경우 |

    - **사용자가 직접 고른 주제는 거르지 않는다.** 막는 대상은 **자동으로 뽑힌 주제**뿐이다.
      온디맨드에서 사용자가 "자살 예방"을 골랐으면 그대로 생성한다.
    - ⚠️ **온디맨드에도 자동 선정 경로가 하나 있다.** 요청에 `topic` 이 없으면
      `OnDemandGenerationService.resolveTopic()` 이 위키 대표 태그(`topTopic()`)로 떨어진다 —
      여기는 규칙 적용 대상이다(2026-08-11 우석 지적). 다만 **현재 화면에서는 도달하지 않는다**:
      프론트가 항상 `topic` 을 싣고 공백이면 네트워크 요청 없이 로컬에서 거절한다. 사용자에게
      나가는 위험은 아니고 **API 계약상 열려 있는 구멍**이다.
    - 이 규칙은 개인 Wiki 자동 선정 경로에 적용한다. 아침은 사용자가 검토하지 않고 받으므로
      선정 프롬프트와 발행 안전장치를 함께 유지해야 한다.
    - ⚠️ **프롬프트 규칙만으로는 샌다.** 2단계 선정은 LLM 이라 확률적이고, "정치인 실명"처럼
      목록으로 못 만드는 범주가 특히 그렇다. 실측 비교에서도 새 방식 결과에 정치인 실명이
      들어갔다. **프롬프트 규칙 + 발행 직전 결정적 차단** 두 겹을 권한다.
  - **펜딩("처리중" 슬롯) 제목은 `topic` 이 아니라 `topics[0]` 을 저장한다.** `topic` 은 고정 문구라
    그대로 저장하면 **모든 사용자 슬롯이 같은 문구**가 되어 무엇을 만드는 중인지 안 보인다.
    요청 바디에는 고정 문구를 보내되, `generation_pendings.topic` 에는 실제 첫 주제를 넣는다.
  - `topics` 는 **최대 5개**, 각 항목 500자 이하. **순서가 곧 리포트 안 섹션 순서**다.
  - 비우거나 안 보내면 기존과 똑같이 `topic` 하나짜리 단일 주제 리포트다(회귀 없음).
  - 주제마다 조사를 따로 돌리므로 **개수에 비례해 생성 시간이 늘어난다.** Worker lease(600초) 안에
    끝나야 하고, 사람 수 × 주제 수만큼 워커 처리량이 필요하다(3주제 전환 시 워커 증설 = 우석 몫).
  - `report_type` 은 **`MORNING_BRIEFING`/`ON_DEMAND` 그대로**다. 주제를 여러 개 묶어도 리포트는
    **여전히 1건**이라 생성 유형이 달라지지 않는다. 새 `report_type` 값을 만들지 않는다.
  - **📌 서술 형식이 두 경로에서 갈린다 — 가르는 값은 `report_type` 이다.**

    | `report_type` | 서술 형식 |
    |---|---|
    | `MORNING_BRIEFING` | 주제 3개를 **독립 섹션으로 나열**(번호 매김). 섹션 간 연결을 만들지 않는다 |
    | `ON_DEMAND` | 주제 간 **연결 관계를 분석해 하나로 통합 서술** |

    Service 는 이미 `report_type` 을 보내고 있어 **새 플래그를 만들 필요가 없다.** 다만 현재 이 값은
    저장·에코만 되고 생성 파이프라인까지 내려가지 않으므로(`agent/`·`domain/` 에 없음),
    **agent 쪽 배선이 필요하다**(김기용).

  - **❓ 미결 — 온디맨드의 `topic` 대표 문구가 정해지지 않았다.** 아침은 `"오늘의 관심사 브리핑"` 으로
    정해졌지만 온디맨드는 사용자가 "지금 생성"을 누른 맥락이라 같은 문구가 어색하다. 이 값은
    **카드 제목 재료로 사용자에게 보이므로** 아무거나 넣으면 안 된다. 정해지면 이 줄을 지운다.

- **특정 관심분야 리포트 (`INTEREST_BUNDLE`) — 채택하지 않음 (2026-08-11 최종)**

  agent 에는 구현돼 있다. `generation_scope="INTEREST_BUNDLE"` + 활성 `user_interests.id` UUID인
  `interest_id`를 보내면, agent 가 관심사 루트와 Wiki 1홉 노드 최대 2개를 접수 시점 Job에 고정하고
  발행 Snapshot에 `source_interest_id`·`interest_profile_id`·`bundle_keywords`로 실제 범위를 돌려준다.

  - **🔁 08-10 에 "깊게 파기"로 재채택됐다가 08-11 에 다시 걷혔다.** 08-07 철회 사유가 아침에만
    해당한다고 보고, **사용자가 직접 눌러 받는 온디맨드 전용** 기능으로 되살렸다(service-api #72,
    프로필 모달 service-web #70, 프롬프트 가드 + 벤치마크 10/10). 그리고 **하루 만에 제거했다**
    (service-web #74 → service-api #80, 이 순서). 철회 사유는 아래 세 가지다(2026-08-11 우석).

    1. **역할이 겹친다.** (B) 전환으로 "위키 기반 자동 선정"을 아침 브리핑이 담당하게 됐다.
    2. **온디맨드를 단일 `topic` 경로로 단순화한다.** Delta 도 같은 흐름으로 계정 설정으로 옮겼다.
    3. **선택 모달이 위키 태그 원본을 그대로 노출한다** — 파편이 포함된 목록을 사용자가 보게 된다.

    **agent 구현·벤치마크는 지우지 않고 보존한다.** 없어지는 것은 Service 호출부뿐이라,
    재채택하면 그 호출부만 복원하면 된다. 되살릴 가능성이 있는 쪽을 급히 지울 이유가 없다.

    ⚠️ **이 기능은 이제 네 번 뒤집혔다**(08-07 세 번 + 08-10 재채택 + 08-11 철회). 재논의가 나오면
    **먼저 아래 두 개의 🔴 부터 확인할 것** — 그 둘은 제품 판단이 아니라 구조적 제약이라, 논의를
    다시 시작해도 결론이 바뀌지 않는다.

  - **Service 는 쓰지 않는다. 아침·온디맨드 둘 다 위 `topics[]`·단일 `topic` 으로 간다.**
    08-07 하루에 세 번 뒤집혔다 — 13:34 채택 → 14:34 철회 → 17:15 재채택(아침·온디맨드 모두) →
    **19:00 철회**. 그때 철회 사유가 아래 두 가지이고, 재논의 때 같은 자리로 돌아오지 않도록 남긴다.
  - **🔴 저장한 `interest_id` 는 반드시 썩는다 — 재채택이 막힌 결정적 이유.** 관심 Profile 은 재계산할
    때마다 **기존 active 를 retired 로 내리고 새 Profile 을 만든다**(`interest_profiles.py`).
    `user_interests` 가 `profile_id` 에 CASCADE 로 묶이고 PK 가 `gen_random_uuid()` 라
    **재계산 때마다 모든 `interest_id` 가 새로 발급된다.** 사용자가 "미리 골라 저장"한 UUID 는
    다음 재계산에 retired 를 가리켜 **409 `ACTIVE_INTEREST_REQUIRED` 로 조용히 실패한다.**
    → 사용자 선택은 **UUID 가 아니라 키워드 이름으로 저장해야** 하고, 그러면 `topics[]` 가 정답이다.
  - **🔴 "상위 3개"를 보낼 필드가 없다.** `interest_id` 는 **단수 1개**이고 `topics` 는 동시 전송 금지다.
    3개를 쓰려면 `interest_ids: list[UUID]` 신설이 필요한데, `topics[]` 로 가면 그 작업이 통째로 없어진다.
  - **⚠️ `INTEREST_BUNDLE` 의 "연결 노드"는 점수 상위가 아니다.** 루트의 **근거 문서에서 양방향 1홉으로
    연결된** 노드를 가져온다(`interest_bundles.list_related_nodes`). 점수 2·3위가 루트와 문서를
    공유하지 않으면 아예 안 들어온다. 그래서 "관심사 상위 3개를 함께 다룬다"는 제품 정의와 맞지 않는다.
    온디맨드의 "주제 간 연결"은 **수집한 기사 내용에서 LLM 이 찾는 것**으로 정의됐다(08-07 김기용).
  - **둘은 동시에 못 보낸다** — agent 스키마가 `INTEREST_BUNDLE에서는 topics를 함께 보낼 수 없습니다`
    로 거부한다(`app/schemas/mvp.py` `model_validator`). 그래서 택일이었다.
  - **방향이 다르다.** `topics[]` 는 관심사 **여러 개를 한 장에** 묶고, `INTEREST_BUNDLE` 은 관심사
    **하나를 연결 키워드까지 깊게** 판다. 아침 브리핑 제품 정의("밤사이 쌓인 소식을 아침 5분에")가
    전자라서 `topics[]` 를 골랐다.
  - **결과 통제권도 다르다.** `INTEREST_BUNDLE` 의 이웃 키워드는 사용자가 고르는 게 아니라 위키
    관계(LLM이 추출해 둔 것)에서 자동으로 딸려오고, 프롬프트가 이웃을 독립 섹션으로 나누지 않아
    본문에 녹아든다 → 무관한 주제가 섞여도 눈에 잘 안 띈다. 사용자가 결과를 검토하지 않고 그냥
    받는 자동 리포트에서는 이 예측 불가능성이 더 위험하다(2026-08-07 김기용 분석).
  - 프리즈 이후 재논의 대상으로 남긴다. 그때 필요한 `interest_id` 는 아래 대응표를 보면 된다.

  📌 **재채택하려면 Service 쪽에서 되살릴 것** (08-11 제거분, agent 는 그대로 있다):
  `GenerationRequest.interestBundle()` 팩토리 · `OnDemandGenerationService.generateBundleForUser()` ·
  `GenerationTriggerRequest.interestTagId` · 프로필 깊게 파기 모달(service-web).

- **`interest_id` = Service `GET /api/wiki/tags` 응답의 `tagId`** — 별도 조회 API가 필요 없다.
  Service 는 이미 이 값을 받고 있다. 2026-07-29 명명 결정으로 agent 필드 `interest_id`·`topic` 을
  `tagId`·`tag` 로 리네임해 내려주고 있어 이름만 달라 보일 뿐 같은 값이다
  (`WikiTag.tagId` = `@JsonAlias("interest_id")`).

  | agent 필드 | Service 노출 이름 | 비고 |
  |---|---|---|
  | `interest_id` | `tagId` | `INTEREST_BUNDLE` 을 쓰게 되면 이 값을 그대로 넣으면 된다 |
  | `topic` | `tag` | 온보딩에서 사용자가 고르는 "topic"과는 다른 개념이라 리네임했다 |

  ⚠️ 온보딩 `selected_category_ids`·`selected_topic_ids` 와는 **다른 ID 공간**이다.
  `topics[]` 에 넣는 값은 이 id 가 아니라 **태그 이름(`tag`)** 이다 — 아침(사용자가 고른 이름)도,
  온디맨드(`topTags(3)` 으로 뽑은 상위 3개 이름)도 마찬가지다. UUID 는 어느 경로에도 들어가지 않는다.
- **온보딩 첫 리포트 = Service 소유 경로 (`ONBOARDING`)**
  - Service는 컨텍스트에 `onboarding_reports_managed_by_service=true`를 보내 Agent의
    레거시 관심사별 자동 등록을 끈다.
  - 이어서 선정한 실제 Topic마다 `POST /generations`를 최대 3회 호출하고
    `report_type=ONBOARDING`을 싣는다.
  - 멱등키는 `onboarding:{user_id}:slot:{1..3}`이며, Service가 펜딩 행과 화면 상태를 소유한다.
  - 필드를 생략하는 구버전 Service에만 Agent의 기존 자동 등록을 유지한다.

### 4.3 버전 관리 (핵심)
- `context_version`은 **사용자별로 단조 증가**해야 한다. 같거나 작은 값 재전송 → `STALE_CONTEXT_VERSION`.
- **구현:** service-db `users.agent_context_version`을 사용자 행 lock 아래 +1하고, 같은 트랜잭션에 Outbox payload를 적재한다.
- `STALE_CONTEXT_VERSION(409)`의 `details[0].current_context_version`에 **agent가 지금 저장하고 있는 버전**이 담긴다.
  → Service는 이 값 + 1로 한 번만 재전송하면 반영된다(왕복 1회로 수렴).
- 이 409를 **그냥 삼키면 안 된다.** service-db의 `users.agent_context_version`은 agent와 독립 카운터라
  "이미 최신"이 아니라 "카운터가 어긋남"인 경우가 있고, 이때 삼키면 온보딩 관심사가 조용히 유실된다
  (2026-08-06 실제 발생). 재전송 후에도 409면 그때 "이미 최신"으로 처리한다.

### 4.4 순서·실패 정책
- **순서 불변식:** 특정 사용자의 `generations` 이전에 그 사용자의 `context`가 반드시 한 번 반영돼 있어야 한다.
- **실패 시(agent 다운·응답 유실):** 가입 커밋에는 `service.agent_context_outbox`가 함께 남는다. 커밋 직후 전송이 실패하면
  lease 기반 폴링 워커가 같은 버전·payload를 지수 backoff로 at-least-once 재전송한다. 프로세스 중단 시에도 만료 lease를 재-claim한다.
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
| 컨텍스트 | `agent_context_version` + Transactional Outbox 재시도 | 소라·영현 | ✅ |
| 변환 경계 | Gateway = `{success,data,error}` 변환 지점 확정 | 소라·영현 | ⬜ |
| 내부 인증 | Agent 전용 opaque Bearer 토큰 + 네트워크 격리 | 전원 | ✅ |
| 차단 ID | `blocked_*_ids` 실제 연결(삭제 기능) | 소라·송우 | ⬜(개인화 고도화) |

**다음 스텝 (08-04 갱신):** ~~결정 1(B/C) 동의~~ ✅ (C) 확정 → ① `reports` 테이블(본문 보존, GAP-3/4 이행) V4 마이그레이션(영현) ② 클리핑·조회 API 중계 + claim/ack HTTP 클라이언트(소라) ③ 생성 트리거 스케줄러 — service 책임(송우 가이드 §3.4, 담당 확정 필요) ④ 컨텍스트 버전·Transactional Outbox 재시도 구현 완료.
