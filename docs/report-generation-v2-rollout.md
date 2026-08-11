# 리포트 생성 루프 V2 전환 계약

> 승인 기준일: 2026-08-12
>
> 범위: Report Builder의 **본문 생성 루프**(조사 이후 ~ 저장 이전)
>
> 제외: Wiki 읽기 루프(`wiki-loop-v2-rollout.md`), Wiki 쓰기·유지 루프, 수집 Worker

## 1. 배경

읽기 루프 V2(`langgraph_v2`)가 근거를 **어디서 얼마나** 가져오는지를 개선했다면,
이 문서는 가져온 근거로 **무엇을 쓰는지**를 다룬다. 리포트 품질 불만의 원인은
근거 부족만이 아니라 생성 루프의 입도(granularity)에 있다.

V1 생성 그래프(`agent/graph.py`의 `build_report_generation_graph`)에서 실측된
구조적 한계는 다음 네 가지다.

| # | 한계 | 근거 |
|---|---|---|
| 1 | **주제 처리가 노드 안에 숨어 있다** | `research`·`load_context`·`generate`가 각각 내부에서 `for topic in topics`를 돈다. 주제 단위로 관측하거나 개입할 지점이 그래프에 없다 |
| 2 | **품질 루프가 리포트 전체 단위 1회** | `route_after_review`는 리포트 전체를 `generate`로 되돌린다. 주제 3개 중 1개가 나빠도 전체를 다시 쓰거나 그대로 발행한다 |
| 3 | **재작성이 근거를 다시 보지 않는다** | 재생성은 같은 Context에 교정 지시만 덧붙인다. "근거가 얕다"는 지적은 재작성으로 해결되지 않는다 |
| 4 | **근거 없는 주제가 조용히 사라진다** | `covered_topics`에서 빠진 주제는 섹션 자체가 없어진다. 일반론 오염은 막지만, 사용자는 "3개 요청했는데 2개 왔다"를 본다 |

V2는 이 네 가지를 그래프 구조로 해소한다. **기존 구현을 삭제하거나 제자리에서
교체하지 않는다** — 읽기·유지 루프 V2와 동일한 동배포·버전 고정 방식을 쓴다.

## 2. 버전 계약

| 값 | 의미 |
|---|---|
| `legacy_v1` | 기존 단일 그래프 실행 경로(`agent/graph.py`) |
| `langgraph_v2` | 주제별 서브그래프 fan-out 실행 경로 |

- 환경변수 `GENERATION_PIPELINE_VERSION`이 **새 Job의** `generation_pipeline_version`을 정한다.
- Job Payload에 값이 고정되므로 배포 중 기본값이 바뀌어도 접수된 Job의 의미와
  재시도 결과는 달라지지 않는다.
- **버전 필드가 없는 과거 Job은 `legacy_v1`로 해석한다.** 이 규칙은 기본값과
  무관하다 — 이미 접수돼 대기 중인 Job이 새 경로로 바뀌면 재시도 결과가
  달라지기 때문이다.
- 읽기 루프 버전(`read_pipeline_version`)과 **독립적으로** 조합된다. V2 생성
  루프는 주제별 조사에 `research_context_for_version`을 그대로 호출하므로 읽기
  V1·V2 어느 쪽과도 맞물린다.

### 2.1 기본값 결정 (2026-08-12 우석)

`GENERATION_PIPELINE_VERSION`의 **기본값은 `langgraph_v2`** 다.

읽기·유지 루프 V2는 `legacy_v1` 기본값으로 배포한 뒤 단계적으로 전환했다. 생성
루프는 데모까지 검증 기간이 충분하다는 판단에 따라 처음부터 V2를 기본값으로
둔다. 롤백은 `GENERATION_PIPELINE_VERSION=legacy_v1`로 되돌린 뒤 새 Job부터
적용하는 방식이며, **실행 중인 Job의 버전은 바꾸지 않는다.**

## 3. 실행 계약

```text
legacy_v1
  research → load_context → generate | change_history → review → persist
  (주제 루프는 각 노드 내부, 품질 루프는 리포트 전체 단위 1회)

langgraph_v2
  plan_topics
    → [주제별 서브그래프 fan-out — Send API]
         research_topic → assess_topic → draft_section
           → critique_section ─(revise)─┐
                │                        │
                └────────(pass)──────────┴→ grade_section
    → assemble
    → final_review
    → persist
```

### 3.1 주제별 서브그래프

각 주제가 **독립적으로** 조사 → 초안 → 검토 → 재작성을 돈다.

- `research_topic` — `research_context_for_version`으로 그 주제의 근거만 모은다.
  실행 중 예외는 그 주제만 `evidence: none`으로 떨어뜨리고 다른 주제를 막지 않는다.
- `assess_topic` — 확보한 근거를 `focus_documents_on_topic`으로 주제에 좁히고
  `select_generation_context`로 상한을 적용한다. 근거가 0건이면 초안을 만들지
  않고 곧장 `grade_section`으로 간다.
- `draft_section` — **섹션 하나**를 생성한다. 리포트 전체가 아니라 이 주제
  몫이므로 프롬프트가 짧고 근거 대비 본문 비율이 높다.
- `critique_section` — 이 섹션의 인용만 원문과 대조한다(`review_report` 재사용).
- `revise` — 지적을 교정 지시로 붙여 **그 섹션만** 다시 쓴다.
  주제별 상한 `GENERATION_SECTION_MAX_REVISIONS`(기본 2)까지.
- `grade_section` — 최종 등급을 붙인다: `ok` · `thin`(근거는 있으나 얕음) ·
  `no_evidence`(근거 없음).

### 3.2 근거 없는 주제를 감추지 않는다 (한계 #4)

`no_evidence` 주제는 본문에서 지우지 않고 **커버리지 노트**로 남긴다.

```markdown
### {주제}

이번 브리핑에서는 이 주제를 뒷받침할 새 근거를 찾지 못했습니다.
```

일반론으로 채우는 것(V1 이전 실측 사고: 없는 발언을 지어냄)과 조용히 삭제하는
것(V1 현재) 사이의 선택지다. **사실을 만들지 않으면서 요청한 주제 수를 지킨다.**
노트 문구는 LLM이 아니라 코드가 만든다 — 이 문장에는 사실 주장이 없어야 한다.

### 3.3 assemble

주제별 섹션을 하나의 `GeneratedReportContent`로 합친다. **LLM을 부르지 않는다.**

- 제목·요약: `ok`/`thin` 섹션의 제목·요약에서 조립한다.
- 본문: `### {주제}` 제목과 함께 요청 순서대로 잇는다.
- 인용: 섹션별 `citation_references` 합집합(중복 제거, 순서 보존).
- `content_tags`: 섹션 태그 합집합.

합치는 단계에서 LLM을 부르면 주제별로 검증한 문장이 다시 흔들린다.

### 3.4 final_review

조립된 전체 리포트를 한 번 더 검토한다. **여기서는 재작성으로 돌아가지 않는다** —
섹션 단위 재작성이 이미 끝났고, 전체를 되돌리면 V1의 문제(#2)가 되돌아온다.
지적은 결과 Payload에 기록해 발행 후 확인 가능하게 남긴다.

### 3.5 change_history(델타) 경로

**V2는 델타 경로를 다루지 않는다.** `change_history_enabled=True` Job은
`generation_pipeline_version`과 무관하게 V1 그래프로 실행한다. 델타는 정형
섹션과 before/after 수치를 다루는 별도 서브그래프라 섹션 fan-out과 의미가
다르고, 검증되지 않은 조합을 만들 이유가 없다.

## 4. 신뢰성 계약

읽기·유지 루프 V2와 동일하다.

- 한 주제의 실패가 다른 주제나 리포트 전체를 막지 않는다.
- Job Payload 누락처럼 명시적인 입력 오류만 영구 실패로 분류한다.
- 모델 출력 파싱 오류를 포함한 그 밖의 실행 오류는 재시도 정책을 적용한다.
- 원문·Secret은 Trace나 Job 결과에 저장하지 않는다.
- 저장 계약(`prag_007` → `report_018` → `report_020` → `report_021`)은 V1과
  **동일한 함수**를 호출한다. 저장 알고리즘을 복제하지 않는다.

## 5. 관측

Job 결과 Payload에 `section_trace`를 추가한다. 주제마다 다음을 담는다.

| 키 | 의미 |
|---|---|
| `topic` | 주제 문자열 |
| `grade` | `ok` \| `thin` \| `no_evidence` |
| `evidence_count` | 초안 생성에 실제로 넣은 근거 수 |
| `revisions` | 섹션 재작성 횟수 |
| `critique_outcome` | 마지막 검토 판정(`pass`/`revise`/`unavailable`) |
| `latency_ms` | 그 주제 전체 소요 시간 |

`evidence_trace`·`research_stats`(V1과 동일 키)는 그대로 유지한다.

## 6. 환경변수

| 이름 | 기본값 | 의미 |
|---|---|---|
| `GENERATION_PIPELINE_VERSION` | `langgraph_v2` | 새 Job의 생성 루프 버전 |
| `GENERATION_SECTION_MAX_REVISIONS` | `2` | 주제별 섹션 재작성 상한 |
| `GENERATION_TOPIC_CONCURRENCY` | `3` | 주제 동시 실행 상한 |

## 7. 출시 순서

기본값이 `langgraph_v2`이므로 읽기 루프와 순서가 다르다.

1. 결정적 테스트(`uv run pytest`)를 통과시킨 뒤 배포한다.
2. 배포 직후 **첫 정기 실행 결과**를 확인한다 — 주제 수 대비 섹션 수,
   `section_trace`의 `grade` 분포, 지연 시간.
3. 회귀가 보이면 `GENERATION_PIPELINE_VERSION=legacy_v1`로 되돌린다.
   진행 중 Job은 고정 버전으로 마친다.
4. `bench/report_generation_v2/`로 V1·V2를 같은 입력에 대해 비교 평가한다.
   실제 Provider를 호출하므로 케이스 수와 예상 비용을 먼저 고지한 뒤 실행한다.

## 8. 미해결

- **주제 간 중복**: 주제별로 따로 쓰므로 두 섹션이 같은 사건을 다룰 수 있다.
  `assemble`이 LLM 없이 합치기 때문에 중복 제거는 하지 않는다. 실측으로 문제가
  확인되면 인용 참조 겹침 기준의 코드 규칙을 먼저 검토한다.
- **비용**: 주제마다 검토·재작성이 붙어 LLM 호출이 늘 수 있다. 반대로 전체
  재생성이 사라져 상쇄되는 부분이 있다. §7-4 벤치로 실측한다.
