# Feature facade 실행 경계 개선 내역

기준일: 2026-07-21

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
- DB 연결, 주입된 Repository, Service 인스턴스처럼 런타임에 결합되는 구현은 `shared.feature_runtime.execute_feature_implementation`으로 실행한다.
- 하나의 트랜잭션이 여러 세부 기능 ID를 함께 만족하는 경우에는 쓰기를 반복하지 않는다. 상위 facade를 실제 실행 경계로 사용하고 세부 기능 함수는 같은 구현을 재사용할 수 있는 합성 위임 경계로 둔다.

## 적용 결과

- 전체 명세 기능: 625개
- 실행 가능한 기능 함수: 63개(MVP 완료 62개 + `SCH-009`)
- 명시적 미구현 스텁: 562개
- facade 구현 포함: 0개
- 외부 모듈의 `features/` 직접 import: 0개

표의 적용 방식은 다음 의미다.

- `실행`: 운영 또는 개발 런타임이 공개 `api.py`의 기능 함수를 실제 호출한다.
- `합성`: 실제 동작은 상위 트랜잭션·그래프에 포함되며, 기능 함수는 같은 구현을 독립 호출할 수 있는 위임 경계다. 중복 쓰기를 피하기 위해 런타임에서 별도 재실행하지 않는다.
- `기존`: 이미 facade와 실제 구현이 연결되어 있어 정합성만 확인했다.

## 기능별 목록

| 기능 ID | 공개 facade | 구현 모듈 | 적용 방식 |
|---|---|---|---|
| `SVC-001` | `app/routers/service/api.py` | `features/context.py` | 실행 |
| `SVC-002` | `app/routers/service/api.py` | `features/wiki.py` | 실행 |
| `SVC-003` | `app/routers/service/api.py` | `features/wiki.py` | 실행 |
| `SVC-008` | `app/routers/service/api.py` | `features/generation.py` | 실행 |
| `SVC-013` | `app/routers/service/api.py` | `features/jobs.py` | 실행 |
| `SVC-014` | `app/routers/service/api.py` | `features/jobs.py` | 실행 |
| `WSE-001` | `domain/personal_wiki/source_events/api.py` | `features/ingestion.py` | 합성 |
| `WSE-011` | `domain/personal_wiki/source_events/api.py` | `features/idempotency.py` | 합성 |
| `WSE-013` | `domain/personal_wiki/source_events/api.py` | `features/status.py` | 합성 |
| `PWIKI-002` | `domain/personal_wiki/documents/api.py` | `features/commands.py` | 실행 |
| `PWIKI-003` | `domain/personal_wiki/documents/api.py` | `features/queries.py` | 실행 |
| `PWIKI-006` | `domain/personal_wiki/documents/api.py` | `features/versions.py` | 실행 |
| `PWIKI-007` | `domain/personal_wiki/documents/api.py` | `features/provenance.py` | 합성 |
| `PWIKI-008` | `domain/personal_wiki/documents/api.py` | `features/deduplication.py` | 합성 |
| `PWIKI-011` | `domain/personal_wiki/documents/api.py` | `features/normalization.py` | 합성 |
| `PWE-001` | `domain/personal_wiki/embeddings/api.py` | `features/chunking.py` | 합성 |
| `PWE-002` | `domain/personal_wiki/embeddings/api.py` | `features/chunking.py` | 합성 |
| `PRAG-003` | `domain/personal_wiki/retrieval/api.py` | `features/hybrid.py` | 실행 |
| `PRAG-006` | `domain/personal_wiki/retrieval/api.py` | `features/context.py` | 실행 |
| `PRAG-007` | `domain/personal_wiki/retrieval/api.py` | `features/citations.py` | 실행 |
| `INT-001` | `domain/interests/api.py` | `features/extraction.py` | 실행 |
| `INT-002` | `domain/interests/api.py` | `features/classification.py` | 실행 |
| `INT-005` | `domain/interests/api.py` | `features/scoring.py` | 실행 |
| `INT-011` | `domain/interests/api.py` | `features/recalculation.py` | 실행 |
| `COL-002` | `infrastructure/sources/connectors/api.py` | `features/naver.py` | 실행 |
| `COL-003` | `infrastructure/sources/connectors/api.py` | `features/gdelt.py` | 실행 |
| `COL-004` | `infrastructure/sources/connectors/api.py` | `features/news_api.py` | 실행 |
| `GSP-004` | `infrastructure/sources/processing/api.py` | `features/normalization.py` | 실행 |
| `GSP-006` | `infrastructure/sources/processing/api.py` | `features/deduplication.py` | 실행 |
| `GSP-015` | `infrastructure/sources/processing/api.py` | `features/safeguards.py` | 실행 |
| `BAMBI-001` | `agent/bambi/api.py` | `features/orchestration.py` | 실행 |
| `BAMBI-004` | `agent/bambi/api.py` | `features/retrieval.py` | 실행 |
| `BAMBI-005` | `agent/bambi/api.py` | `features/retrieval.py` | 실행 |
| `BAMBI-008` | `agent/bambi/api.py` | `features/generation.py` | 실행 |
| `BAMBI-009` | `agent/bambi/api.py` | `features/generation.py` | 실행 |
| `BAMBI-011` | `agent/bambi/api.py` | `features/citations.py` | 실행 |
| `BAMBI-012` | `agent/bambi/api.py` | `features/context.py` | 실행 |
| `BAMBI-018` | `agent/bambi/api.py` | `features/persistence.py` | 실행 |
| `BAMBI-020` | `agent/bambi/api.py` | `features/events.py` | 실행 |
| `BAMBI-021` | `agent/bambi/api.py` | `features/safeguards.py` | 실행 |
| `WORKER-001` | `workers/api.py` | `features/global_source_collector.py` | 실행 |
| `WORKER-002` | `workers/api.py` | `features/personal_wiki_builder.py` | 실행 |
| `WORKER-003` | `workers/api.py` | `features/bambi_generation.py` | 실행 |
| `SW-004` | `app/routers/service_worker/api.py` | `features/snapshots.py` | 실행 |
| `SW-009` | `app/routers/service_worker/api.py` | `features/acknowledgements.py` | 실행 |
| `WBA-001` | `agent/wiki_builder/api.py` | `features/orchestration.py` | 실행 |
| `WBA-003` | `agent/wiki_builder/api.py` | `features/documents.py` | 실행 |
| `JOB-001` | `domain/jobs/api.py` | `features/lifecycle.py` | 합성 |
| `JOB-002` | `domain/jobs/api.py` | `features/lifecycle.py` | 합성 |
| `JOB-006` | `domain/jobs/api.py` | `features/progress.py` | 합성 |
| `JOB-007` | `domain/jobs/api.py` | `features/results.py` | 합성 |
| `JOB-010` | `domain/jobs/api.py` | `features/idempotency.py` | 합성 |
| `WC-001` | `workers/runtime/api.py` | `features/queue.py` | 실행 |
| `WC-002` | `workers/runtime/api.py` | `features/queue.py` | 합성 |
| `WC-006` | `workers/runtime/api.py` | `features/retry.py` | 합성 |
| `WC-009` | `workers/runtime/api.py` | `features/idempotency.py` | 합성 |
| `WC-013` | `workers/runtime/api.py` | `features/concurrency.py` | 합성 |
| `SCH-009` | `scheduler/api.py` | `features/wiki.py` | 기존 |
| `DB-002` | `infrastructure/persistence/api.py` | `features/personal_wiki.py` | 합성 |
| `DB-003` | `infrastructure/persistence/api.py` | `features/personal_wiki.py` | 합성 |
| `DB-004` | `infrastructure/persistence/api.py` | `features/personal_wiki.py` | 합성 |
| `DB-005` | `infrastructure/persistence/api.py` | `features/personal_wiki.py` | 합성 |
| `DB-026` | `infrastructure/persistence/api.py` | `features/jobs.py` | 합성 |

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
| 관심사 재계산 | `INT-011 → INT-001/002/005` |
| 최신 정보 API·Collector Worker | `COL-* → GSP-*` |
| Worker 상주 소비 루프 | `WC-001` |

`PWIKI-007/008/011`, `PWE-001/002`, `DB-002/003/004`, `JOB-*` 등은 각각 독립 SQL을 다시 실행하면 같은 트랜잭션의 문서·Version·Chunk·Job을 중복 생성할 수 있다. 따라서 현재는 상위 실행 경계가 실제 구현을 한 번만 호출하고, 세부 facade는 동일 구현을 재사용하는 합성 위임 계약으로 유지한다.

`DB-005`의 저장 함수와 스키마는 유지하지만, `PWE-004/005`가 MVP 실행 경로에서 보류되어 실제 Embedding 생성·저장은 호출하지 않는다. 이 상태는 `agent-api-mvp-scope.md`의 보류 결정과 동일하다.

## 검증 항목

- 완료 기능 62개가 `NotImplementedError` 스텁이 아닌지 MVP 체크리스트와 자동 대조한다.
- `api.py`에 함수 구현이 없는지 검사한다.
- 기능 함수가 정확히 하나의 `api.py`에서 공개되는지 검사한다.
- 외부 모듈이 `features/` 구현 파일을 직접 import하지 않는지 검사한다.
- 위임형 완료 기능 57개가 동기·비동기 구현을 실행하고 올바른 `FeatureResult.feature_id`를 보존하는지 검사한다.
- 프롬프트, 모델, LangGraph 노드·엣지는 변경하지 않았으므로 유료 LLM 벤치마크 재실행 대상이 아니다.
