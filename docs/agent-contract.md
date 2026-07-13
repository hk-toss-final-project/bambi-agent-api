<!--
이 문서는 service-api(Spring) ↔ agent-api(FastAPI) 연동 계약 "초안(제안서)"이다.
작성: 소라(연동 담당). 근거: 송우/LLM팀이 07-10 커밋한 실제 코드(app/routers, app/schemas, app/services).
목적: 우석·소라·송우 "agent 계약 경계 확정" 미팅의 입력물. 확정 전까지 FINAL 아님.
-->

# Agent 연동 계약 (초안 / 경계 확정용)

> 상태: **DRAFT — 확정 대기.** 이 문서는 소라(연동)가 송우(코어)가 이미 커밋한 코드를 근거로 정리한 제안서다.
> "송우와 agent 계약 경계 확정 — 우석·소라" 액션의 논의 자료로 쓴다. 아래 **§4 확정 필요 결정**이 정해지면 FINAL로 승격한다.
>
> 소유 경계: **agent-api 코어(엔드포인트·스키마·생성 로직) = 송우/LLM팀**, **연동(Gateway·계약·AI 로그) = 소라**, **창구 = 우석**.

---

## 1. 이 문서가 다루는 범위

- service-api(Spring, 영현/우석) 가 agent-api(FastAPI, 송우) 를 **어떤 규약으로 호출하는지**.
- 그 사이 다리인 **AgentGateway(소라, Spring 쪽)** 의 호출·에러·타임아웃 규약.
- **AI 로그** 를 무엇으로/어디에 남기고 관리자 화면(admin-web, 소라)이 무엇을 읽는지.
- 아키텍처 원칙(팀 지도 기준): **agent-api·db 는 내부 전용, 프론트는 agent 직접 호출 금지.** 프론트 → nginx → next/spring 만 외부 노출. 따라서 **agent-api 를 호출하는 주체는 항상 Spring** 이다.

이 문서는 agent-api **내부 구현을 규정하지 않는다.** 내부 구현은 송우 소유다.

---

## 2. 지금 실제로 있는 것 (송우 커밋 코드 기준, 사실)

> 아래는 추정이 아니라 `bambi-agent-api` 커밋 `3d5aa7f ✨ Implement FastAPI MVP routes` 의 실제 코드다.

### 2.1 경로 규약
- 내부 API Prefix: **`/internal/v1`** (`API_PREFIX` 환경변수로 변경 가능, 기본값 `/internal/v1`).
- 시스템 엔드포인트는 prefix 없이 `/system/*`.
- 추적 헤더: `X-Request-ID`, `X-Trace-ID` (없거나 형식 오류면 agent-api 가 생성).

### 2.2 시스템 API
| Method | Path | 설명 |
|---|---|---|
| GET | `/system/live` | 프로세스 생존 |
| GET | `/system/ready` | 컴포넌트 준비 상태 (준비 안 되면 503 `SERVICE_NOT_READY`) |
| GET | `/system/version` | 앱 이름·버전·환경 |

### 2.3 Service API 연동 (Spring → agent-api) — **전부 비동기 Job 방식**
| Method | Path | 성공 | 설명 |
|---|---|---:|---|
| PUT | `/internal/v1/users/{user_id}/context` | 200 | 사용자 컨텍스트 upsert (버전 역행 시 409 `STALE_CONTEXT_VERSION`) |
| POST | `/internal/v1/users/{user_id}/wiki-sources/clippings` | 202 | 웹 클리핑 → Job 등록 |
| POST | `/internal/v1/users/{user_id}/wiki-sources/urls` | 202 | **URL 저장 → Job 등록** |
| POST | `/internal/v1/users/{user_id}/wiki-sources/content-marks` | 202 | 위키마킹 → Job 등록 |
| POST | `/internal/v1/users/{user_id}/generations` | 202 | **밤비 콘텐츠 생성 → Job 등록** |
| GET | `/internal/v1/jobs/{job_id}` | 200 | Job 상태·진행률 |
| GET | `/internal/v1/jobs/{job_id}/result` | 200 | 완료 결과 (미완료면 409 `JOB_RESULT_NOT_READY`) |

응답(`202 Accepted`) 예시 — `AcceptedJobResponse`:
```json
{ "job_id": "…", "feature_id": "SVC-008", "status": "queued", "request_id": "…", "created_at": "…" }
```

### 2.4 응답·에러 포맷 (agent-api 현재 방식)
- **성공**: `{success, data, error}` 래핑 **없이** Pydantic 모델을 그대로 반환.
- **에러**: 공통 `ErrorResponseSchema` —
  ```json
  { "code": "JOB_NOT_FOUND", "message": "…", "request_id": "…", "retryable": false, "details": [] }
  ```
- 검증 실패: `422` + `code: "REQUEST_VALIDATION_ERROR"`.
- 정의된 에러 코드: `REQUEST_VALIDATION_ERROR(422)`, `STALE_CONTEXT_VERSION(409)`, `JOB_NOT_FOUND(404)`, `JOB_RESULT_NOT_READY(409)`, `PUBLISH_SNAPSHOT_NOT_FOUND(404)`, `PUBLISH_SNAPSHOT_MISMATCH(409)`, `SERVICE_NOT_READY(503)`, `INTERNAL_SERVER_ERROR(500)`.

> ⚠️ 이 포맷은 팀 공통 규약 `{ success, data, error }` + 코드표(`AUTH_INVALID_TOKEN`, `VALIDATION_ERROR` 등)와 **다르다.** → §4 GAP-2.

### 2.5 현재 한계 (사실, 미팅에서 반드시 공유)
- `AgentApiMvpService` 는 **인메모리 저장소**다. 프로세스 재시작 시 컨텍스트·Job·결과가 사라진다.
- **Job 을 완료(`COMPLETED`)로 바꾸는 Worker 가 아직 없다.** `complete_job()` 을 호출하는 코드가 저장소에 없어서, 지금 `/generations` 를 호출하면 Job 은 `queued` 에 머물고 `/jobs/{id}/result` 는 계속 `409 JOB_RESULT_NOT_READY` 를 반환한다.
- 생성 기능 함수(`svc_008` 등)는 `raise NotImplementedError` **stub** 이다.
- **결론: 지금 agent-api 만으로는 "즉시 카드 1장" E2E 가 불가능하다.** 무엇으로 이 갭을 메울지가 이 계약의 핵심.

---

## 3. P0 목표가 요구하는 것 (팀 지도 기준)

팀 지도 1차 MVP 흐름: `④ Mock Agent → ⑤ 관심사·요약 → ⑥ 즉시 카드 1장`.

- **"즉시(즉시 카드 1장)"** = 사용자가 URL/본문을 저장하면 그 요청 흐름 안에서 카드가 바로 나와야 한다.
- 브리핑 7-5 확정 응답 포맷(Mock 이 만들어야 할 결과):
  ```json
  {
    "summary": "저장한 자료의 핵심 요약입니다.",
    "interests": ["AI Agent", "LangGraph", "RAG"],
    "card": {
      "title": "저장한 자료 기반 브리핑 카드",
      "summary": "이 카드는 사용자가 저장한 URL/본문을 기반으로 생성되었습니다.",
      "whyForYou": "최근 저장한 자료에서 AI Agent 관련 관심사가 추론되었기 때문입니다.",
      "sourceUrl": "{input.url}"
    }
  }
  ```
- 이 결과가 **관심사·요약(agent schema) + 카드(service schema) + AI 로그** 로 저장되어 피드/관리자 화면에 뜬다.

---

## 4. 확정 필요 결정 (← 미팅 안건, 이게 이 문서의 핵심)

> 각 항목은 소라 제안 + 결정 주체를 표기했다. 확정되면 값 채우고 FINAL 로 올린다.

### GAP-1. P0 는 동기인가 비동기인가? **(가장 중요)**
- 현실: 팀 지도는 "즉시 카드"(동기 느낌) ↔ 송우 코드는 비동기 Job + Worker 미구현.
- **소라 제안(택1):**
  - **(A) 동기 처리 엔드포인트를 P0 한정으로 추가** — 예: `POST /internal/v1/users/{user_id}/generations:sync` 또는 기존 `generations` 가 `?mode=sync` 일 때 결과까지 담아 `200` 반환. Spring 은 한 번 호출로 카드를 받는다. Worker/Kafka 는 P1.
  - **(B) 비동기 유지 + Spring 이 짧게 폴링** — `202` 받고 `/jobs/{id}/result` 를 즉시 재조회. Worker(동기 실행이라도) 를 P0 에 넣어 Job 을 바로 `COMPLETED` 로. Gateway 가 폴링을 흡수해 영현 저장 API 에는 동기처럼 보이게.
  - **소라 추천: (A).** P0 범위가 "Kafka 비동기는 P1" 이므로 폴링/Worker 인프라를 P0 에 넣는 건 과함. 단 **엔드포인트 신설은 송우 코어 영역** → 송우가 넣거나, 송우 위임 시 소라가 넣는다.
- **결정 주체: 송우(코어) + 우석(창구). 소라 입력.**

### GAP-2. 응답 포맷 — 공통 규약 `{success,data,error}` 경계는 어디서 변환?
- agent-api = `{code,message,request_id,retryable,details}` / 팀 공통 = `{success,data,error}`.
- **소라 제안:** agent-api 는 **내부 전용**이니 지금 포맷 유지. **AgentGateway(소라, Spring)가 경계에서 변환** — agent-api 응답을 받아 프론트로 나갈 땐 Spring 공통 `{success,data,error}` 로 감싼다. 에러 코드도 Gateway 에서 팀 코드표로 매핑(예: agent `INTERNAL_SERVER_ERROR` → `AGENT_UNAVAILABLE` 등).
- **결정 주체: 소라 + 영현(Spring 공통 응답).**

### GAP-3. 생성 결과 스키마 매핑 — 7-5 포맷 ↔ 송우 스키마
- 송우 `GenerationRequest` = `{ idempotency_key, topic, content_type, language }`. `JobResultResponse.result` 는 자유 `dict`.
- 7-5 는 `{ summary, interests[], card{title,summary,whyForYou,sourceUrl} }`.
- **소라 제안:** `JobResultResponse.result` (또는 GAP-1(A) 동기 응답 body) 안에 7-5 구조를 그대로 담는다. 저장 API 입력(URL/본문)이 `topic`/`payload` 중 어디로 들어갈지 송우와 필드 확정 필요.
- **결정 주체: 송우(코어 스키마) + 소라.**

### GAP-4. 저장 주체·스키마 분리 — 누가 무엇을 어디에 쓰나
- 팀 지도: 1개 postgres, **service schema(원본/최종/로그)** ↔ **agent schema(요약/관심사/임베딩)**.
- **소라 제안:** 관심사·요약·임베딩 = agent schema(송우). 카드 최종본·피드·사용자행동 = service schema(영현). **AI 로그**(입력→결과)는 §5 참조.
- **결정 주체: 송우 + 영현. 소라 조율.**

---

## 5. AgentGateway 규약 (소라, Spring 쪽) — 초안

> GAP-1 결정에 따라 (A)/(B) 중 하나로 확정. 아래는 (A) 동기 기준 초안.

- **위치:** service-api(Spring). 영현 저장 API 가 동기로 호출하는 컴포넌트.
- **호출:** `POST {AGENT_API_BASE}/internal/v1/users/{userId}/generations`(동기 모드) — body 에 URL/본문·idempotency_key·topic.
- **헤더:** `X-Request-ID`, `X-Trace-ID` 전파. (내부 인증은 MVP 제외 — 내부망 한정.)
- **타임아웃:** 제안 **3초**(Mock 이라 빠름). 초과 시 `AGENT_TIMEOUT` 로 매핑, 저장 자체는 성공시키되 카드는 "생성 대기"로 폴백할지 영현과 합의.
- **실패 처리:** agent-api 5xx/타임아웃 → Gateway 가 팀 공통 에러(`AGENT_UNAVAILABLE`)로 변환, 저장 트랜잭션 처리 정책(롤백 vs 카드만 지연)은 영현과 합의.
- **응답 검증:** 받은 JSON 이 7-5 스키마(summary/interests/card) 를 만족하는지 Gateway 에서 검증 후 저장.

---

## 6. AI 로그 계약 (소라) — 초안

- **무엇을:** Agent 처리 1건당 `{ 입력(url/본문·userId·요청ID), 출력(summary/interests/card), 모델/모드(mock), 소요시간, 성공여부, 에러코드 }`.
- **어디에:** service schema 의 AI 로그 테이블(관리자 화면이 Spring 통해 조회하므로 service 쪽이 자연스러움) vs agent schema. → GAP-4 와 함께 확정.
- **누가 남기나:** **AgentGateway(소라)** 가 호출 전후로 남기는 것을 기본안으로 제안(agent-api 내부 실패도 Gateway 관점에서 기록 가능).
- **관리자 API(소라):** `GET /api/admin/ai-logs`(Spring) — 관리자 권한, 페이지네이션, 팀 공통 `{success,data,error}`. admin-web(소라)이 이 API 를 그린다.

---

## 7. 미확정 → 다음 액션

| # | 질문 | 결정 주체 | 상태 |
|---|---|---|---|
| GAP-1 | P0 동기 vs 비동기, 동기 엔드포인트 누가 추가 | 송우·우석 | ⬜ |
| GAP-2 | `{success,data,error}` 변환 경계 = Gateway 확정 | 소라·영현 | ⬜ |
| GAP-3 | 저장 입력→topic/payload, result 에 7-5 담기 | 송우·소라 | ⬜ |
| GAP-4 | 관심사/요약/카드/로그 저장 스키마 분담 | 송우·영현 | ⬜ |
| — | AI 로그 위치·주체·관리자 API 시그니처 | 소라·영현 | ⬜ |

**다음 스텝:** 이 초안을 우석에게 전달 → 송우와 GAP-1·3 확정 → 확정값 반영해 FINAL 승격 → AgentGateway/AI 로그 구현 착수.
