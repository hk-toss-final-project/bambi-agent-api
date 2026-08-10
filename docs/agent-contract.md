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

### 4.2-1 온보딩 관심사 시드 + 웰컴 리포트 (콜드스타트)
- **시드 (WSE-014, agent 자동):** `signup_interests`가 있으면 context 수신 시 agent가 선택을 시드 Markdown으로 합성해 사용자별 단일 활성 `onboarding_seed` Head의 Version·Personal Wiki Build Job으로 **자동 접수**한다. `selected_topic_ids`는 Agent DB에 미리 관리한 결정론적 정의·특징·활용을 사용하고 정식 복합 명칭을 분해하지 않는다. `category=null` 그룹의 Topic은 사용자 추가 키워드이며 taxonomy 별칭→기존 Wiki→사용자 서명 캐시→LLM 일반론→결정론 폴백 순으로 해석한다. 같은 선택은 현재 Version을 재사용하고 변경된 선택은 다음 Version+Full Rebuild로 이전 시드 전용 노드를 제거한다. 빌드 완료 후 INT-011 훅이 관심사 프로필을 파생시킨다. 컨텍스트 저장과 분리된 best-effort이고 Service의 추가 호출은 불필요하다.
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
- **⭐ 아침 브리핑·온디맨드 둘 다 `topics[]` 로 간다 (2026-08-07 저녁 이송우·김기용 확정)**

  `generation_scope`는 `SINGLE_TOPIC`(기본) 그대로 두고 `topics` 배열만 채운다.
  **두 경로 모두 주제 3개**이고, 다른 건 **누가 3개를 고르느냐**뿐이다.

  | 경로 | 주제 3개를 고르는 주체 | 보내는 것 |
  |---|---|---|
  | 아침 브리핑 | **사용자** (설정에서 미리 골라 저장) | `topic="오늘의 관심사 브리핑"` + `topics=[사용자가 고른 3개]` |
  | 온디맨드 | **시스템** (위키 태그 점수 상위 3개 자동) | `topic`=대표 문구 + `topics=[상위 3개]` |

  ⚠️ **이 표는 07-31~08-07 낮 계약과 아침·온디맨드가 서로 뒤바뀌어 있다.** 그때는 아침이 자동,
  온디맨드가 사용자 선택이었다. 옛 코드·문서를 보고 반대로 구현하지 않도록 여기 못 박는다.

  - **⚠️ `topics`를 채우면 `topic` 의 의미가 바뀐다.** 평소 `topic` 은 agent 의 **실제 검색어**지만
    (2026-08-05 항목 참고), `topics` 가 있으면 `topic` 은 **카드 제목·`generation_topic` 표시용**이 되고
    본문이 다루는 주제는 `topics` 목록이 결정한다. 두 규칙이 정반대라 헷갈리기 쉬우니 여기 못 박는다.
    그래서 고정 문구를 `topic` 에 넣어도 된다 — 그 문구로 검색하지 않는다.
  - **🚨 그래서 `topics` 가 비면 Service 는 요청 자체를 보내지 않는다.** `topic` 만 남는 순간 그 고정
    문구가 **다시 실제 검색어가 되어** 엉뚱한 기사를 물어온다(2026-08-05 유림 확인). 사용자가 아침
    관심사를 아직 고르지 않았을 때가 정확히 이 상황이라 실제로 발생한다. Service 가 건너뛴다.
  - **⭐ 아침 브리핑 `topics` 폴백 3단계 (2026-08-08, 황유림 지적으로 확정)**

    위 규칙만 두면 **선택 화면이 나오기 전에는 아무도 안 골랐으므로 아침 브리핑이 전면 중단된다.**
    화면이 나온 뒤에도 설정을 건드리지 않은 사용자는 계속 못 받는다. 그래서 Service 는 이 순서로 채운다.

    1. **사용자가 미리 고른 3개** — 선택 화면·저장소가 생긴 뒤
    2. 없으면 **사용자 등록 관심사**(온보딩에서 고른 것 + 직접 추가한 것) 최근 3개
       (`InterestRepository.findByUserIdAndDeletedAtIsNullOrderByCreatedAtDesc`)
    3. 그것도 없으면 **건너뛴다**

    - **2단계에 위키 태그 상위 3개를 쓰지 않는다.** 저장한 글에서 뽑힌 파편이 상위를 차지하기
      때문이다(agent-api #21 — 폭염 기사 1건으로 관심사 상위가 `서울`·`온열질환`·`질병관리청`이 되고
      아침 브리핑이 `서울` 로 나갔다). **아침은 사용자가 결과를 검토하지 않고 그냥 받는 경로라
      파편이 가장 위험한 자리다.** 등록 관심사는 사용자가 직접 고른 값이라 파편이 섞이지 않는다.
    - 08-08 유림님 필터(도구·출처로만 등장한 노드를 관심사 후보에서 제외)가 배포됐지만
      **기존 위키에는 아직 적용되지 않아** 재빌드 전까지 이 판단은 그대로 유효하다.
    - **`topics[]` 가 UUID 가 아니라 이름 문자열이라 이 폴백이 가능하다.** 온보딩 관심사는 위키 태그와
      **ID 공간이 다르지만**(아래 참고) 이름은 그대로 쓸 수 있다. `INTEREST_BUNDLE` 이었다면 불가능했다.
    - 이 폴백 덕분에 **선택 화면은 아침 발행의 blocker 가 아니다.** 화면이 없어도 아침은 정상 발행된다.
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

- **특정 관심분야 리포트 (`INTEREST_BUNDLE`) — 채택하지 않음 (2026-08-07)**

  agent 에는 구현돼 있다. `generation_scope="INTEREST_BUNDLE"` + 활성 `user_interests.id` UUID인
  `interest_id`를 보내면, agent 가 관심사 루트와 Wiki 1홉 노드 최대 2개를 접수 시점 Job에 고정하고
  발행 Snapshot에 `source_interest_id`·`interest_profile_id`·`bundle_keywords`로 실제 범위를 돌려준다.

  - **Service 는 쓰지 않는다. 아침·온디맨드 둘 다 위 `topics[]` 로 간다.** 08-07 하루에 세 번 뒤집혔다 —
    13:34 채택 → 14:34 철회 → 17:15 재채택(아침·온디맨드 모두) → **19:00 최종 철회**. 마지막 철회 사유가
    아래 두 가지이고, 재논의 때 같은 자리로 돌아오지 않도록 남긴다.
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
- **온보딩 첫 리포트 = agent 자체 경로 (`ONBOARDING`)**
  - 위 시드(WSE-014)가 끝나면 **agent가 스스로** 첫 리포트 생성을 건다. **Service 트리거가 아니다** — `POST /generations` 호출이 없다.
  - 그래서 이 경로의 Snapshot은 `report_type`을 **agent가 `ONBOARDING`으로 채운다**(Service가 실어 보낼 값이 없으므로).
  - 값 이름은 Service가 정했다(2026-08-06). agent는 이 문자열을 하드코딩해 넣기만 한다.
  - ⚠️ **2026-07-20 MVP 문서에 있던 "웰컴 리포트 = Service가 `idempotency_key=welcome:{user_id}`로 1회 호출"은 폐기됐다.** Service에 그 호출은 구현되지 않았고, 같은 자리를 위 agent 자체 경로가 채운다. 옛 문서를 보고 Service 쪽에서 중복 트리거를 만들지 않도록 여기 남긴다.

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
