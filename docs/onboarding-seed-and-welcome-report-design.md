# 온보딩 콜드스타트 설계 — 관심사 시드 + 웰컴 리포트

> 상태: **Part B 컨텍스트 시드·Service 소유 온보딩 리포트 구현 완료** · 작성일 2026-08-04 · 갱신일 2026-08-11
> 목적: 가입 직후 "관심사 0개 · 리포트 0개"인 콜드스타트를 해소한다.
> (1) 온보딩에서 고른 Category·Topic을 **관심사 시드 입력원**으로 정식 편입해 프로필을
> 채우고, (2) 가입 즉시 **온보딩 리포트를 최대 3개** 생성해 첫 화면을 비지 않게 한다.
> 상위 설계: [wiki-interest-subscription-design.md](wiki-interest-subscription-design.md)
> (입력원 → Wiki → 관심사 프로필 → 구독의 단방향 파생 원칙).
> "확인됨"은 코드·스키마로 검증한 사실, "결정 필요"는 팀이 정해야 하는 항목이다.
> 용어: 영어 `seed`의 한국어 표기는 **시드**로 통일한다.

---

## 1. 문제

가입·온보딩 직후 사용자는 아무것도 저장한 적이 없다. 그런데:

- 관심사 프로필은 Wiki에서 파생되는 materialized view라(원칙 3), Wiki가 비면 관심사도 **0개**다.
- 리포트는 명시 요청(`topic`+`content_type`)이 있어야 생성되므로 첫 화면에 보여줄 게 **없다**.

온보딩에서 고른 Category·Topic이 있는데도 화면이 비어 있는 게 현재 상태다.

## 2. 현황 — 무엇이 배선되어 있고 무엇이 안 되어 있나 (확인됨)

| 대상 | 상태 |
|---|---|
| 온보딩 선택 저장 | `signup_interests`(라벨: `category`/`topics` 문자열)와 `selected_category_ids`·`selected_topic_ids`(안정 ID)+`interest_taxonomy_version`이 `user_context_snapshots`에 **저장만** 됨. `domain` 어디서도 소비하지 않음 — 사실상 죽은 데이터. ([mvp.py:81·105](../app/schemas/mvp.py), 커밋 661f5ab·7986e24) |
| 관심사 재계산 `int_011` | **활성 Wiki Build가 없으면 `ActiveWikiRequiredError`로 하드 실패.** ([recalculation.py:68-73](../domain/interests/features/recalculation.py)) |
| 행동-전용 후보 경로 | `int_005`는 Wiki에 없어도 양의 신호가 쌓인 Topic을 후보로 추가할 수 있음([scoring.py:221-250](../domain/interests/features/scoring.py)) — 하지만 `int_011`이 그 앞에서 활성 Wiki를 요구하므로 **가입 직후엔 도달 불가.** |
| 리포트 생성 워커 | `report_generation` Job payload에 `topic`+`content_type` **필수**([report_generation.py:35-39](../workers/features/report_generation.py)). 가입 시 자동 발행 트리거 없음. |
| Wiki 편입 파이프라인 | `wiki_source_events` → wiki build 그래프. 일반 원본은 LLM `classify_source_for_wiki`가 원문을 읽고, `onboarding_seed`는 `resolve_onboarding_context`에서 정식 Topic DB 컨텍스트와 추가 키워드 해석 결과를 만든 뒤 결정적으로 Entity·Concept로 분류한다. 이후 Build 계획·저장·Snapshot·INT-011은 같은 경로를 재사용한다. |

**결론**: 온보딩 시드가 프로필로 이어지려면 반드시 **활성 Wiki Build를 만드는 경로**여야 한다. "신호만" 넣는 방식(좋아요 경로)은 `int_011`의 활성 Wiki 요구 때문에 콜드스타트에서 작동하지 않는다. → 유연님이 고른 **"온보딩 시드 입력원"** 방향이 현재 계약과 정합하는 유일한 선택.

## 3. 핵심 제약 3개

1. **`int_011`은 활성 Wiki Build를 요구한다** → 시드는 Wiki 노드 + Build 스냅샷을 남겨야 한다.
2. **일반 Wiki 노드는 원문 텍스트에서 LLM이 만든다** → 정식 taxonomy 토픽은 Agent DB의 검수된 컨텍스트로 결정적으로 Concept를 만들고, 사용자 추가 키워드만 기존 taxonomy·Wiki·캐시로 해석되지 않을 때 구조화 LLM 해석을 허용한다(§4.2, 결정 S1).
3. **Service taxonomy Snapshot과 선택 ID를 함께 사용한다** — Service가 먼저 동기화한 taxonomy의 name·name_en·keywords와 Agent DB의 검수된 alias를 추가 키워드 exact match에 사용한다. 표시용 원문은 `signup_interests`, 정식 정체성·dedup은 `selected_*_ids`에서 취한다.

## 4. Part B — 온보딩 시드 입력원

### 4.1 흐름

```mermaid
graph LR
    ON["온보딩 선택<br/>signup_interests(라벨)+selected_ids(안정ID)"]
      -->|"컨텍스트 upsert 시<br/>새 입력원 이벤트"| EV["wiki_source_events<br/>type=onboarding_seed"]
    EV --> SEED["시드 Wiki 노드 물질화<br/>(§4.2 결정 S1)"]
    SEED --> BUILD["활성 Wiki Build 스냅샷<br/>seed=true 표시"]
    BUILD -->|"int_011 재계산 훅"| PROF["관심사 프로필<br/>user_interests"]
    REAL["이후 실제 저장/클리핑"] --> EV2["정상 입력원 이벤트"] --> BUILD2["real 근거 Build"]
    BUILD2 -->|"재계산 시 시드보다<br/>강한 근거가 상위로"| PROF
```

### 4.2 시드 Wiki 노드 생성 방식 — **결정 S1**

`int_011`이 읽을 활성 Wiki Build는 필요하지만, 정식 taxonomy 선택을 일반 LLM
분류에 넣을 필요는 없다. 최종 방식은 **검수된 결정적 컨텍스트 + 제한된 커스텀
키워드 해석 + 기존 Build 파이프라인**이다.

- `onboarding_seed` 원본과 합성 Markdown은 멱등·감사·출처 추적을 위해 그대로 저장한다.
- `agent.onboarding_topic_contexts`는 taxonomy 버전·Topic ID별 Definition,
  Characteristics, Applications, Alias를 DB Migration 시드로 보존한다. 정식 Topic은
  이 값을 읽어 LLM 없이 **Concept 노드**로 만든다.
- 사용자 추가 Topic은 taxonomy 이름·alias·keyword와 기존 Wiki 제목·alias를 먼저
  결정적으로 대조하고, `agent.user_custom_topic_contexts` 캐시도 없을 때만 Wiki Build
  Worker가 구조화 LLM 해석을 수행한다. 결과는 Entity/Concept kind와 일반론적 맥락만
  허용하며 최신 사실·수치·의료·투자 판단은 만들지 않는다. 실패하면 사용자 선언
  문구로 폴백한다.
- 이후 `build_wiki_plan` → 문서/Version/출처/Chunk/Snapshot 저장 → INT-011 재계산은
  일반 원본과 동일한 경로를 재사용한다. 별도 DB 쓰기 경로를 만들지 않는다.
- 유효한 `labels`가 없으면 조용히 빈 Wiki를 만들지 않고 Build를 실패시켜 손상된 입력을 드러낸다.

따라서 정식 44개 Topic은 비용과 비결정성이 없고, 커스텀 키워드만 사용자별 문맥으로
한 번 해석한 뒤 캐시를 재사용하면서 기존 저장 계약을 유지한다.

#### 기존 LLM 방식에서 확인된 부작용과 해소 (2026-08-04 E2E 검증)

(b)로 실제 파이프라인을 돌려 보니, Wiki Builder가 고른 주제 노드와 함께
**시드 문서 자체를 가리키는 상위 개념 노드**("온보딩 관심 주제")를 만들었다.
이 노드는 선택 주제 전부와 연결돼 degree가 가장 높아 **관심사 1위**를 차지했다.

| 순위 | Topic | score |
|---|---|---|
| 1 | 온보딩 관심 주제 | 1.000 |
| 2~4 | 금리 / 반도체 / 생성형 AI | 0.710 |

사용자가 선언한 관심사가 아니므로 기존에는 INT-001에서 걸러냈다. 규칙은
**"시드가 유일한 근거인 노드는 온보딩 라벨과 맞을 때만 관심 후보로 인정한다"** —
라벨은 시드 Version의 `source_metadata.labels`에서 읽는다. 실제 저장이 같은
노드에 쌓이면 근거 종류가 늘어 이 판정에서 빠지므로 그때는 후보로 되살아난다.
결정적 분류 적용 후에는 애초에 합성 문서 제목인 `온보딩`·`온보딩 관심 주제 시드`가
노드 후보가 되지 않으며, 이 필터는 과거 Build와 방어적 검증을 위해 유지한다.

### 4.3 점수 가중치 — 결정 S2

시드 노드가 실제로 관심사로 **떠오르되, 실제 근거가 쌓이면 자연히 밀려나야** 한다.

- `int_005._SOURCE_TYPE_WEIGHTS`에 `onboarding_seed` 항목 추가(잠정 `0.15` — `url`과 동급, `web_clipping` 0.2보다 낮게). ([scoring.py:26-34](../domain/interests/features/scoring.py))
- 근거 원문 시각이 없으므로 최신성은 중립값 `_NEUTRAL_RECENCY=0.5`로 들어간다(별도 처리 불필요).
- 실제 클리핑·저장(가중치 0.2~0.6)이 같은/관련 Topic에 쌓이면 재계산 시 자연히 상위로 올라가며 시드는 하위로 내려간다. **시드를 명시 삭제하지 않아도 파생 뷰가 알아서 정리**한다.

### 4.4 프로필 파생

시드 Build가 활성이 되면 기존 **INT-011 자동 재계산 훅**(wiki build 완료 시, [wiki-interest-subscription-design.md](wiki-interest-subscription-design.md) Track A1)이 그대로 동작해 `user_interests`를 채운다. 별도 파생 로직 없음.

### 4.5 라벨·정체성 매핑

- **표시 이름**: `signup_interests[].topics` (없으면 `category`).
- **안정 정체성·dedup·차단 매칭**: `selected_topic_ids`/`selected_category_ids` + `interest_taxonomy_version`을 노드 evidence에 보존. `blocked_interest_ids`(svc_001)와 같은 ID 공간을 쓰면 차단이 시드에도 바로 적용된다.
- `SignupInterest` docstring은 "`user_interests`의 `(category, topic)` 쌍으로 확장"을 언급하지만([mvp.py:84-85](../app/schemas/mvp.py)), **프로필 직접 쓰기(단방향 위배)가 아니라 Wiki 시드를 거쳐 파생**하는 것으로 해석한다.

### 4.6 원칙 1과의 관계

원칙 1은 "사용자 의사가 개입된 저장 행위만 Wiki가 된다"이다. 온보딩 선택은 콘텐츠 저장은 아니지만 **명시적 사용자 의사**다. 따라서 `onboarding_seed`를 원칙 1의 정식 입력원으로 **추가**하되, 가중치를 낮춰(§4.3) "약한 시드"로 다룬다. 자동 생성물 무단 편입(REPORT-021)과는 무관하다 — 시드는 사용자가 고른 것이다.

### 4.7 멱등·중복·선택 교체

- 온보딩은 여러 번 저장될 수 있다(컨텍스트 재-upsert). 이벤트는
  `(user_id, taxonomy_version, selected_ids, preferred_language, custom keyword 집합)` 기준
  멱등 처리한다.
- 사용자 Namespace마다 활성 `onboarding_seed` 원본 Head는 하나다. 선택이 바뀌면 새
  Head를 추가하지 않고 같은 Head의 새 Version으로 저장한다. 과거 Version은 감사
  이력으로 보존하지만 Full Rebuild·관심사 라벨은 활성 Head의 현재 Version만 읽는다.
- 빠진 선택이 시드 외의 실제 원본 근거가 없으면 현재 Wiki와 관심사에서 제외한다.
  실제 클리핑 근거가 있는 동일 노드는 시드 선택에서 빠져도 유지한다.

## 5. Part A — 웰컴 리포트

### 5.1 트리거

온보딩 리포트 생성·멱등성·펜딩 상태는 Service API가 소유한다. Service는 컨텍스트
upsert에 `onboarding_reports_managed_by_service=true`를 보내 Agent의 레거시 자동
등록을 끄고, 온보딩 완료 시 선정한 관심사로 SVC-008을 최대 3회 호출한다.

### 5.2 topic 도출 · content_type

- **topic**: Service의 온보딩 관심사 선정 규칙으로 고른 실제 검색어. 사용자 입력
  Topic을 먼저 고르고, 남은 자리는 선택 Topic 수가 많은 Category 순으로 Category당
  가장 먼저 선택한 Topic 하나만 고른다.
- **content_type**: `interest_news_card`.
- **language**: `preferred_language`.

### 5.3 멱등·실패 격리·비용

- `idempotency_key = f"onboarding:{user_id}:slot:{1..3}"`로 재호출에도 사용자당
  온보딩 리포트가 최대 3개만 생성되게 한다([submit_generation](../app/services/agent_jobs.py) 경로 재사용).
- Job enqueue 실패가 온보딩 저장(컨텍스트 upsert)을 롤백시키면 안 된다 — **best-effort, 실패 격리**. (wiki build 완료 훅이 실패해도 Build를 유지하는 기존 패턴과 동일.)
- 비용: 가입마다 리포트 생성 LLM 호출 최대 3회. 봇 가입·대량 가입 시 비용 급증 가능 → 결정 A3(rate-limit/plan 게이팅 여부).

### 5.4 REPORT-021 준수

웰컴 리포트는 자동 생성물이므로 **사용자가 북마크하기 전엔 Wiki에 편입하지 않는다**([safeguards.py](../agent/report_builder/features/safeguards.py) REPORT-021). Part B 시드와 별개 경로 — 리포트가 관심사 근거로 되먹임되는 자기강화 루프를 막는다.

### 5.5 A와 B의 순서

Service는 먼저 컨텍스트를 upsert해 시드 Job과 사용자 컨텍스트를 접수한 뒤 SVC-008을
호출한다. Wiki Build 완료까지 기다리지는 않으며, 리포트는 전달받은 실제 Topic과 사용자
컨텍스트만으로 독립 실행한다. 시드와 리포트 실패는 서로 격리한다.

## 6. 결정 결과 (확정 2026-08-04)

| ID | 결정 | 결과 |
|---|---|---|
| S1 | 시드 Wiki 노드 생성 방식 | **검수된 결정적 Topic 컨텍스트 + 커스텀 키워드 제한 해석 + 기존 Wiki Build** — 정식 Topic은 Agent DB 시드로 Concept를 만들고, 커스텀 키워드만 taxonomy·Wiki·캐시 미스 때 구조화 LLM으로 Entity/Concept를 판정한다(2026-08-10 개선) |
| S2 | `onboarding_seed` 가중치·최신성 취급 | **0.15**(클리핑 0.2보다 낮게)·중립 최신성 — 결정적 회귀 테스트와 로컬 E2E로 검증 |
| S3 | 시드 명시 삭제 UI 필요 여부 | **자연 하락만** — 실제 저장이 쌓이면 재계산 시 밀려남(별도 삭제 UI 없음) |
| A1 | 웰컴 리포트 `content_type` | **`interest_news_card`**(카드형, 이미 기본값) |
| A2 | 다중 선택 시 topic 선정 | **최대 3개** — 사용자 입력 Topic 우선, 남은 자리는 선택 Topic 수가 많은 Category 순, Category당 최초 선택 Topic 1개 |
| 트리거 | 웰컴 리포트 발행 주체 | **Service**(`POST /generations`, MVP 2026-07-20 결정 준수). Agent는 시드(Part B)만 담당 |
| A3 | 웰컴 리포트 게이팅 | 미결 — 봇·대량 가입 비용은 Service 트리거와 함께 별도 논의 |

구현 현황: Part B(시드)는 `agent-api`에 구현 완료(WSE-014, 44개 DB 컨텍스트,
추가 키워드 캐시·LLM 폴백, 단일 Head Version 교체, Full Rebuild 포함). Part A(온보딩 리포트)는
Service에 위임해 구현했다([service-integration-guide.md](service-integration-guide.md) §3.1,
[agent-contract.md](agent-contract.md) §4.2-1).

## 7. 비목표 (이번 범위 밖)

- 관심사 프로필 직접 편집 UI(단방향 원칙 유지).
- 온보딩 신호를 좋아요 경로(INT-005 신호)로 넣는 방식 — §2 결론대로 콜드스타트에서 작동 안 함.
- taxonomy ID→라벨 서버 사이드 매핑 테이블(현재는 `signup_interests` 라벨로 충분).

## 8. 구현 완료 체크리스트

- [x] `onboarding_seed` 입력원 이벤트·단일 활성 Head·Version 멱등(§4.7).
- [x] 정식 44개 Topic 컨텍스트 Migration 시드와 구조화 Wiki 물질화.
- [x] 사용자 추가 키워드 alias·기존 Wiki·캐시·LLM·일반론 폴백.
- [x] 선택 변경 Full Rebuild와 현재 Version 전용 관심사 라벨 파생.
- [x] `/dev/graphs`의 `resolve_onboarding_context` 노드·가드 테스트 갱신.
- [x] 결정적 단위 테스트와 추가 키워드 LLM 벤치마크 데이터셋·실행기.
- [x] Agent·Service 통합 계약과 Agent DB 카탈로그·컬럼 사전 갱신.
```
