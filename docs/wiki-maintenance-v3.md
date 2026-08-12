# Personal Wiki 유지 루프 V3 구현 계약

> 승인 기준일: 2026-08-12
>
> 범위: Personal Wiki의 주기적 의미 감사, 선택적 내부 복구, 외부 지식 공백 수집,
> Full Rebuild의 LangGraph 내부 단계화
>
> 호환 버전: `legacy_v1`, `langgraph_v2`, `langgraph_v3`

## 1. 목표

`langgraph_v3`는 정기 Full Rebuild를 유지보수 그 자체로 보지 않는다. 활성 Wiki와
삭제되지 않은 원본 Head의 최신 Version을 같은 시점의 Manifest로 읽고 다음 문제를
찾아, 문제를 해결하는 데 필요한 최소 범위만 실행한다.

1. 서로 다른 Page·Source의 의미상 모순과 새 자료가 대체한 오래된 주장
2. 여러 Source에서 반복되지만 canonical Page가 없는 중요한 주제
3. 관련 근거가 있는데도 연결되지 않은 기존 Page 사이의 관계
4. 활성 원본만으로 확정할 수 없어 외부 출처 보강이 필요한 지식 공백

V3는 V1·V2를 삭제하거나 의미를 바꾸지 않는다. Job 등록 시점의
`maintenance_pipeline_version`을 Payload에 고정하고 Worker는 그 값을 실행한다.
초기 배포의 기본값은 검증된 `langgraph_v2`를 유지하며, V3는 환경변수로 선택한
Job부터 canary 실행한다.

## 2. 책임 경계

### 유지 루프가 직접 담당하는 일

- 활성 Wiki Snapshot과 활성 원본 Manifest 고정
- 현재 Snapshot에서 WBA-014 구조 Lint 재계산
- LLM 의미 감사와 결과의 결정적 검증
- 근거가 충분한 누락 Page·관계의 선택적 Wiki Build 계획 생성
- 모순·대체 주장 Metadata의 출처 보존 기록
- 지식 공백별 외부 수집 요청 생성
- 변경된 Wiki 문서 Embedding과 관심사 Profile 후처리

### 다른 루프로 위임하는 일

- 외부 검색 결과 URL의 본문 취득은 `personal_wiki_url` Worker가 담당한다.
- 취득한 본문을 정식 사용자 Source Version으로 저장한 뒤 쓰기 루프가 Wiki에
  반영한다.
- 유지 루프는 외부 검색 요약을 Wiki Page에 직접 복사하지 않는다.

이 경계로 모든 Wiki 내용은 사용자 원본 또는 유지 루프가 수집한 정식 Source
Version과 provenance를 갖는다.

## 3. 그래프 계약

### 3-1. 유지 그래프

```text
operational_audit
  → route_operational_action
      ├─ full_rebuild → V3 Full Rebuild Subgraph
      └─ continue
  → load_semantic_snapshot
  → structural_lint
  → generate_global_candidates
  → semantic_lint
  → plan_repairs
  → apply_internal_repairs
  → request_external_research
  → repair_derivatives
  → persist_lint_summary
  → finalize
```

- 원본 삭제·신규 원본·활성 Snapshot 부재처럼 구조 기준선이 달라졌으면 의미 감사
  전에 Full Rebuild를 한 번 수행한다.
- Full Rebuild 뒤에는 새 Snapshot을 다시 읽고 의미 감사를 수행한다.
- 한 Job에서 Full Rebuild는 최대 한 번만 수행한다.
- 의미 감사가 실패하면 기존 활성 Wiki를 변경하지 않고 Job 재시도 정책에 맡긴다.

### 3-2. Full Rebuild Subgraph

```text
load_manifest
  → select_source
  → resolve_onboarding_context
  → classify_source
  → prepare_identity
  → resolve_identity
  → link_relations
  → plan_source
  → accumulate_snapshot
  → select_source (다음 원본이 있으면 반복)
  → validate_snapshot
  → commit_atomic_replacement
  → embed_changed_documents
  → finalize
```

원본은 온보딩 시드 우선 순서로 순차 처리한다. 앞선 원본에서 생성한 canonical
Page와 관계가 뒤 원본의 identity·관계 후보이므로 이 반복은 병렬화하지 않는다.
LLM 단계가 모두 끝나기 전에는 DB Wiki를 변경하지 않으며, 최종 교체는 기존 V1과
같이 하나의 Transaction에서 수행한다.

## 4. 의미 감사 입력과 출력

LLM에는 원본 전체를 무제한 전달하지 않는다. 결정적 단계가 Page·Source·관계와
누락 관계 후보를 안정적인 참조(`P1`, `S1`, `C1`)로 만들고 설정된 개수·문자 상한을
적용한다. Job 결과와 Trace에는 원문을 저장하지 않는다.

허용 문제 코드는 다음과 같다.

| 코드 | 의미 | 자동 처리 |
|---|---|---|
| `contradiction` | 같은 시점·대상에 대해 양립할 수 없는 주장 | 양쪽 출처를 보존하고 warning Metadata 기록 |
| `stale_claim` | 더 최신이고 신뢰 가능한 Source가 이전 주장을 명시적으로 대체 | 대체 관계 Metadata 기록 |
| `missing_topic` | 반복 근거가 있지만 canonical Page가 없음 | 근거 Source 기반 Page·관계 계획 생성 |
| `missing_relation` | 기존 두 Page를 잇는 근거가 있지만 관계가 없음 | 검증 관계 계획 생성 |
| `knowledge_gap` | 활성 원본만으로 설명을 확정할 수 없음 | 외부 수집 요청 생성 |

모든 문제에는 결정적 issue ID, 관련 Page·Source 참조, 짧은 근거, confidence가
필요하다. 원문 인용을 요구하는 수정은 실제 Source 본문에 존재하는 연속 문구만
허용한다. 허구 참조, 허구 인용, 기존 관계 중복, 허용되지 않은 Ontology, confidence
하한 미달 결과는 저장 전에 제외한다.

## 5. 누락 주제와 전역 관계 후보

- 누락 주제는 서로 다른 Source의 반복 근거를 우선한다. 단일 Source 후보는 Page를
  만들 만큼 명시적인 정의와 주요 subject 연결이 있을 때만 허용한다.
- 기존 title·alias와 같은 표면형은 누락 주제로 취급하지 않는다.
- tool·source·단순 mention 역할과 일반 불용어는 자동 Page 후보에서 제외한다.
- 전역 관계는 모든 Page 쌍을 LLM에 넣지 않는다. 어휘·trigram·공유 Source·기존
  Graph 이웃 신호로 상위 후보를 만든 뒤 LLM이 원본 근거를 확인한다.
- 관계 후보 점수와 공동 출현만으로 Edge를 자동 생성하지 않는다.

## 6. 외부 지식 공백 수집

LLM이 `knowledge_gap`으로 판정하고 confidence 기준을 넘긴 항목만 수집한다. 한 유지
Job의 검색 질의와 URL 수에는 상한을 둔다. 검색 결과는 다음 순서로 처리한다.

```text
knowledge_gap
  → 실시간 검색·선별
  → URL별 결정적 source_event_id 생성
  → personal_wiki_url Job 멱등 등록
  → URL Worker가 본문을 Source Version으로 저장
  → 쓰기 루프 Job 등록
```

동일 issue·URL 조합은 다음 주 유지 Job에서도 같은 event ID를 사용해 중복 수집하지
않는다. 검색이나 URL 등록 실패는 해당 공백 결과에 기록하되, 이미 검증된 내부 Wiki
수정은 되돌리지 않는다.

## 7. 안전성과 비용 상한

- 자동 모순 처리는 기존 주장을 물리 삭제하거나 출처 없이 덮어쓰지 않는다.
- 내부 Wiki 수정은 최종 WBA-014 Gate를 통과한 뒤 하나의 Transaction으로 반영한다.
- LLM 응답과 외부 검색은 mock으로 단위 테스트하며 `uv run pytest`에서 실제 API를
  호출하지 않는다.
- 의미 감사 Page·Source·후보·입력 문자 수와 research query·URL 수를 설정으로
  제한한다.
- 실제 Provider 벤치마크는 케이스 수·예상 Token·비용을 먼저 알리고 승인 후 실행한다.
- 실행 결과에는 입력 원문 대신 issue code·ID·개수와 선택된 action만 저장한다.

## 8. 출시와 롤백

1. V3 코드와 그래프 레지스트리를 배포하되 새 Job 기본값은 V2로 유지한다.
2. 명시적으로 V3를 선택한 canary 사용자에서 issue precision, 잘못된 자동 수정,
   수집 URL 적합도, 지연·Token·비용을 기록한다.
3. 기준을 통과한 뒤 `WIKI_MAINTENANCE_PIPELINE_VERSION=langgraph_v3`로 새 Job
   기본값만 전환한다.
4. 문제가 생기면 환경변수를 `langgraph_v2` 또는 `legacy_v1`로 되돌린다. 이미
   등록된 Job은 Payload에 고정된 버전으로 완료한다.

## 9. 완료 조건

- `legacy_v1`과 `langgraph_v2` 테스트·결과 계약이 유지된다.
- `langgraph_v3`의 의미 감사 네 영역이 독립 LangGraph 노드로 보인다.
- V3 Full Rebuild가 기존 V1 `rebuild_runner` 한 노드에 위임되지 않고 내부 단계
  그래프로 실행된다.
- 누락 Page·관계는 출처 있는 선택적 Build로 반영되고, 지식 공백은 정식 URL Source
  수집과 쓰기 루프로 이어진다.
- `/dev/graphs`, 설정 허용값, Job 등록 검증, Worker 버전 라우팅이 V3와 동기화된다.
- 최소 10개 의미 감사 벤치마크 데이터셋과 실행기가 있으며 실제 실행 여부와 비용을
  사실대로 보고한다.
