# Feature facade 실행 경계 개선 내역

기준일: 2026-07-22

## 목적

명세상 구현 완료로 표시됐지만 기능 함수가 `NotImplementedError` 스텁이거나, 실제 런타임이 기능 facade를 우회하던 경로를 정리했다. 공개 경로와 구현 위치는 다음 규칙으로 통일한다.

```text
Router / Service / Worker / Graph
                ↓
        <기능 영역>/api.py
                ↓
       <기능 영역>/features/*.py
                ↓
기존 Service / Repository / Provider / 순수 함수
```

- `api.py`는 구현을 갖지 않고 `features/` 함수의 import와 `__all__`만 유지한다.
- 실제 기능 함수와 MVP 주석은 `features/`에 둔다.
- 외부 계층은 `features/`를 직접 import하지 않는다.
- DB 연결, Repository, Service, Provider처럼 런타임에 결합되는 의존성은 typed 인자나 `Protocol`로 기능 함수에 명시한다.
- 완료 기능은 호출자의 `payload["implementation"]`을 실행하지 않고, 기능 함수가 검증·변환·오케스트레이션을 소유한다.
- 하나의 트랜잭션에 여러 기능이 포함되면 상위 실행 경계가 각 기능 facade를 정확히 한 번씩 합성해 중복 쓰기를 막는다.
- `execute_feature_implementation` 호환 위임은 이번 작업에서 제외한 `agent/bambi/**`에만 유지한다.

## 적용 결과

- 전체 명세 기능: 625개
- 실행 가능한 기능 함수: 59개(MVP 완료 58개 + `SCH-009`)
- 명시적 미구현 스텁: 566개
- facade 구현 포함: 0개
- 외부 모듈의 `features/` 직접 import: 0개

표의 적용 방식은 다음 의미다.

- `소유`: 기능 함수가 typed 인자와 명시적 의존성으로 검증·변환·오케스트레이션을 소유한다.
- `제외(호환 위임)`: 사용자 요청에 따라 변경하지 않은 Bambi 구현으로, 기존 범용 실행기를 유지한다.

## 로직 소유 전환 (2026-07-22)

"실행" 방식 중 호출자가 `payload={"implementation": ...}`로 자기 로직을 주입하던 경로는
기능 함수가 로직을 소유하지 않는 형식적 통과 지점이었다. 판별 기준을 다음으로 정한다.

> 새 호출처에서 기능 함수만 호출해도 해당 기능이 실제로 수행되는가?

이 기준에 따라 관심사(INT) 영역을 첫 템플릿으로 전환한 뒤, 제외 대상 외 완료 기능 전체에 같은 원칙을 적용했다.

- `INT-001`: 관심 키워드 추출 로직을 `agent/wiki_builder/features/interests.py`에서
  `domain/interests/features/extraction.py`로 이동하고, `int_001(documents, *, limit)`
  typed 시그니처가 로직을 직접 소유한다. `extract_interest_candidates`는 제거했다.
- `INT-011`: 재계산 오케스트레이션(문서 조회 → INT-001 추출 → Profile 저장)을
  `features/recalculation.py`가 소유한다. 저장소는 `InterestProfileRepository`
  Protocol로 주입받고, 활성 Wiki 부재는 `ActiveWikiRequiredError` 도메인 오류로
  구분해 앱 계층이 HTTP 409로 변환한다.
- `INT-002`, `INT-005`: implementation 주입 경로의 항등 람다(받은 값을 그대로
  반환)는 실제 분류·점수 로직이 아니므로 명시적 미구현 스텁으로 복원하고 MVP
  체크리스트에서 해제했다. 해당 능력 중 Category 부여·Wiki 기반 점수는 INT-001
  추출 내부에 포함되어 있다.
- `app/services/interests.py`는 INT-011 호출과 Pydantic 응답 검증, HTTP 오류
  변환만 담당하는 얇은 계층이 됐다.

- Service·Service Worker: Router가 `FeatureRequest` 구현 콜백을 만들지 않고 `SVC-*`, `SW-*` typed facade를 직접 호출한다.
- Personal Wiki·Retrieval·Wiki Builder: `PWIKI-*`, `PWE-*`, `PRAG-*`, `WBA-*`가 명시적 저장소·Connection·Runner 계약으로 실행된다.
- 외부 소스: `COL-* → GSP-*` 수집·정규화·중복 제거·Global Namespace 보호 체인을 facade 호출로 구성한다.
- Job·Worker Runtime·Persistence: `JOB-*`, `WC-*`, `DB-*`, `WSE-*`가 생성·Claim·진행률·결과·재시도·상태 전이를 직접 소유한다.
- Worker·Scheduler 진입점: `WORKER-*`, `WC-001`, `SCH-009`가 typed 실행 인자를 받아 하위 facade를 호출한다.
- `PWIKI-011`, `WC-009`는 독립 로직 없이 값을 그대로 반환하던 항등 위임이어서 `INT-002/005`와 함께 명시적 스텁으로 복원했다.
- 사용자 지정 제외 범위인 `agent/bambi/**`, `agent/assistant/**`는 변경하지 않았다. 이 중 실제 완료 기능이 있는 Bambi 영역만 기존 범용 실행기 호환 경계를 유지한다.

## 기능별 목록

| 기능 ID | 공개 facade | 구현 모듈 | 적용 방식 |
|---|---|---|---|
| `SVC-001` | `app/routers/service/api.py` | `features/context.py` | 소유 |
| `SVC-002` | `app/routers/service/api.py` | `features/wiki.py` | 소유 |
| `SVC-003` | `app/routers/service/api.py` | `features/wiki.py` | 소유 |
| `SVC-008` | `app/routers/service/api.py` | `features/generation.py` | 소유 |
| `SVC-013` | `app/routers/service/api.py` | `features/jobs.py` | 소유 |
| `SVC-014` | `app/routers/service/api.py` | `features/jobs.py` | 소유 |
| `WSE-001` | `domain/personal_wiki/source_events/api.py` | `features/ingestion.py` | 소유 |
| `WSE-011` | `domain/personal_wiki/source_events/api.py` | `features/idempotency.py` | 소유 |
| `WSE-013` | `domain/personal_wiki/source_events/api.py` | `features/status.py` | 소유 |
| `PWIKI-002` | `domain/personal_wiki/documents/api.py` | `features/commands.py` | 소유 |
| `PWIKI-003` | `domain/personal_wiki/documents/api.py` | `features/queries.py` | 소유 |
| `PWIKI-006` | `domain/personal_wiki/documents/api.py` | `features/versions.py` | 소유 |
| `PWIKI-007` | `domain/personal_wiki/documents/api.py` | `features/provenance.py` | 소유 |
| `PWIKI-008` | `domain/personal_wiki/documents/api.py` | `features/deduplication.py` | 소유 |
| `PWE-001` | `domain/personal_wiki/embeddings/api.py` | `features/chunking.py` | 소유 |
| `PWE-002` | `domain/personal_wiki/embeddings/api.py` | `features/chunking.py` | 소유 |
| `PRAG-003` | `domain/personal_wiki/retrieval/api.py` | `features/hybrid.py` | 소유 |
| `PRAG-006` | `domain/personal_wiki/retrieval/api.py` | `features/context.py` | 소유 |
| `PRAG-007` | `domain/personal_wiki/retrieval/api.py` | `features/citations.py` | 소유 |
| `INT-001` | `domain/interests/api.py` | `features/extraction.py` | 소유 |
| `INT-011` | `domain/interests/api.py` | `features/recalculation.py` | 소유 |
| `COL-002` | `infrastructure/sources/connectors/api.py` | `features/naver.py` | 소유 |
| `COL-003` | `infrastructure/sources/connectors/api.py` | `features/gdelt.py` | 소유 |
| `COL-004` | `infrastructure/sources/connectors/api.py` | `features/news_api.py` | 소유 |
| `GSP-004` | `infrastructure/sources/processing/api.py` | `features/normalization.py` | 소유 |
| `GSP-006` | `infrastructure/sources/processing/api.py` | `features/deduplication.py` | 소유 |
| `GSP-015` | `infrastructure/sources/processing/api.py` | `features/safeguards.py` | 소유 |
| `BAMBI-001` | `agent/bambi/api.py` | `features/orchestration.py` | 제외(호환 위임) |
| `BAMBI-004` | `agent/bambi/api.py` | `features/retrieval.py` | 제외(호환 위임) |
| `BAMBI-005` | `agent/bambi/api.py` | `features/retrieval.py` | 제외(호환 위임) |
| `BAMBI-008` | `agent/bambi/api.py` | `features/generation.py` | 제외(호환 위임) |
| `BAMBI-009` | `agent/bambi/api.py` | `features/generation.py` | 제외(호환 위임) |
| `BAMBI-011` | `agent/bambi/api.py` | `features/citations.py` | 제외(호환 위임) |
| `BAMBI-012` | `agent/bambi/api.py` | `features/context.py` | 제외(호환 위임) |
| `BAMBI-018` | `agent/bambi/api.py` | `features/persistence.py` | 제외(호환 위임) |
| `BAMBI-020` | `agent/bambi/api.py` | `features/events.py` | 제외(호환 위임) |
| `BAMBI-021` | `agent/bambi/api.py` | `features/safeguards.py` | 제외(호환 위임) |
| `WORKER-001` | `workers/api.py` | `features/global_source_collector.py` | 소유 |
| `WORKER-002` | `workers/api.py` | `features/personal_wiki_builder.py` | 소유 |
| `WORKER-003` | `workers/api.py` | `features/bambi_generation.py` | 소유 |
| `SW-004` | `app/routers/service_worker/api.py` | `features/snapshots.py` | 소유 |
| `SW-009` | `app/routers/service_worker/api.py` | `features/acknowledgements.py` | 소유 |
| `WBA-001` | `agent/wiki_builder/api.py` | `features/orchestration.py` | 소유 |
| `WBA-003` | `agent/wiki_builder/api.py` | `features/documents.py` | 소유 |
| `JOB-001` | `domain/jobs/api.py` | `features/lifecycle.py` | 소유 |
| `JOB-002` | `domain/jobs/api.py` | `features/lifecycle.py` | 소유 |
| `JOB-006` | `domain/jobs/api.py` | `features/progress.py` | 소유 |
| `JOB-007` | `domain/jobs/api.py` | `features/results.py` | 소유 |
| `JOB-010` | `domain/jobs/api.py` | `features/idempotency.py` | 소유 |
| `WC-001` | `workers/runtime/api.py` | `features/queue.py` | 소유 |
| `WC-002` | `workers/runtime/api.py` | `features/queue.py` | 소유 |
| `WC-006` | `workers/runtime/api.py` | `features/retry.py` | 소유 |
| `WC-013` | `workers/runtime/api.py` | `features/concurrency.py` | 소유 |
| `SCH-009` | `scheduler/api.py` | `features/wiki.py` | 소유 |
| `DB-002` | `infrastructure/persistence/api.py` | `features/source_ingestion.py` | 소유 |
| `DB-003` | `infrastructure/persistence/api.py` | `features/personal_wiki.py` | 소유 |
| `DB-004` | `infrastructure/persistence/api.py` | `features/personal_wiki.py` | 소유 |
| `DB-005` | `infrastructure/persistence/api.py` | `features/personal_wiki.py` | 소유 |
| `DB-026` | `infrastructure/persistence/api.py` | `features/jobs.py` | 소유 |

## 실제 런타임 경계 변경

| 호출 경로 | 변경 후 facade 경계 |
|---|---|
| Service API 컨텍스트·원본·생성·Job 조회 | `SVC-001/002/003/008/013/014` |
| Service Worker Snapshot 조회·ACK | `SW-004/009` |
| Personal Wiki Graph 저장 | `PWIKI-002` |
| Wiki 목록·상세·Build 조회 | `PWIKI-003/006` |
| Personal Wiki Worker와 개발 즉시 실행 | `WORKER-002 → WBA-001` |
| Bambi Worker와 개발 즉시 실행 | `WORKER-003 → BAMBI-001` |
| Bambi Graph 검색·생성·저장 | `PRAG-* → BAMBI-*` |
| 관심사 재계산 | `INT-011 → INT-001` |
| 최신 정보 API·Collector Worker | `COL-* → GSP-*` |
| Wiki 저장 Transaction | `PWIKI-002 → DB-003 → PWIKI-008/007 → PWE-001/002 → DB-004` |
| Job 생성·Claim·완료·실패 | `JOB-* → DB-026`, `WC-002/006` |
| Worker 상주 소비 루프 | `WC-001 → WC-013 → WORKER-002/003` |
| 조용 시간 Wiki Build 등록 | `SCH-009 → JOB-001` |

저장 Transaction은 호출자가 같은 구현 콜백을 여러 기능 ID에 주입하지 않는다. 상위 기능이 하위 facade를 명시적으로 호출하고, 각 하위 기능은 자신에게 해당하는 검증·변환·SQL만 한 번 수행한다. 이 구조로 기능 ID 추적성과 실제 실행 경계를 일치시키면서 문서·Version·Chunk·Job의 중복 쓰기를 피한다.

`PWIKI-011`, `WC-009`, `INT-002`, `INT-005`는 상위 처리 결과를 그대로 반환하는 것만으로 독립 기능이 구현됐다고 볼 수 없어 완료 목록에서 제외했다. 스텁을 유지해 호출 시 미구현 상태가 명시적으로 드러난다.

`DB-005`의 저장 함수와 스키마는 유지하지만, `PWE-004/005`가 MVP 실행 경로에서 보류되어 실제 Embedding 생성·저장은 호출하지 않는다. 이 상태는 `agent-api-mvp-scope.md`의 보류 결정과 동일하다.

## 검증 항목

- MVP 완료 기능 58개와 별도 구현 `SCH-009`가 `NotImplementedError` 스텁이 아닌지 자동 대조한다.
- `api.py`에 함수 구현이 없는지 검사한다.
- 기능 함수가 정확히 하나의 `api.py`에서 공개되는지 검사한다.
- 외부 모듈이 `features/` 구현 파일을 직접 import하지 않는지 검사한다.
- `execute_feature_implementation`의 운영 코드 사용처가 제외 대상인 `agent/bambi/**`로 제한되는지 검사한다.
- typed 기능 단위 테스트와 Router·Worker·Persistence 통합 테스트로 실제 facade 실행 체인을 검증한다.
- 프롬프트, 모델, LangGraph 노드·엣지는 변경하지 않았으므로 유료 LLM 벤치마크 재실행 대상이 아니다.
