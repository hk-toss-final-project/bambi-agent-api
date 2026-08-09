# LLM Wiki Builder P0~P3 개선 설계와 구현 상태

> 기준일: 2026-08-09
> 범위: 개인 Wiki의 노드 추출, canonical identity, 관계 후보 회수·판정,
> 관계 이력, 품질 검증, 전체 재구성, Embedding 후보 검색과 Graph 검색 확장
> 상태 표기: **연결됨**은 운영 Build 경로에서 호출됨, **구현됨(미연결)**은
> 테스트 가능한 모듈은 있으나 운영 호출 경로가 아직 없음을 뜻한다.

## 1. 개선 목표

기존 Builder의 핵심 문제는 LLM 사용 여부 자체가 아니라 역할이 섞여 있던 것이다.
한 번의 분류 응답이 새 노드 추출과 일부 관계만 반환하면, 관계가 한 건이라도 있다는
이유로 누락 관계 재검토가 생략됐다. 기존 Wiki 전체와 비교할 후보 회수 단계도 없어
온보딩 `날씨`와 후속 클리핑의 `폭염`·`태풍 돌핀`처럼 원문 문자열이 겹치지 않는
관계를 검토할 기회가 없었다.

개선 원칙은 다음과 같다.

1. 노드 **추출 완전성**과 관계의 **사실성 판정**을 분리한다.
2. Embedding·문자열·기존 Graph는 LLM이 검토할 후보의 recall만 높인다.
3. 후보 점수나 같은 문서 공동 출현만으로 Edge를 자동 생성하지 않는다.
4. 관계는 근거, provenance, confidence, review 상태와 수명주기를 함께 보존한다.
5. Graph 품질이 검증되기 전에는 다중 hop 검색 확장을 열지 않는다.

## 2. 현재 Build 흐름

```text
load_source
  → classify
  → prepare_identity → (모호할 때만 resolve_identity)
  → quality_gate
  → recall_candidates
  → link_relations
  → plan
  → validate_plan
  → persist
  → embed
  → finalize
```

- 온보딩 시드는 사용자가 직접 고른 라벨이므로 LLM 분류·관계 판정을 호출하지 않고
  결정적으로 Concept로 저장한다.
- 이후 일반 클리핑을 처리할 때 온보딩 Concept를 `onboarding_anchor` 후보로 넣는다.
  따라서 `날씨`가 원문에 직접 없어도 `폭염`과의 의미 관계를 Linker가 검토할 수 있다.
- `link_relations`는 추출 단계에 관계가 일부 있더라도 항상 실행한다. “관계가 0건일
  때만 재검토”하는 이전 조건은 더 이상 Build Graph의 판단 기준이 아니다.
- `embed` 실패는 이미 저장된 Wiki Build를 되돌리지 않는다. 다음 Build는
  표면형·어휘·trigram·Graph·온보딩 후보로 계속 동작하며 경고를 결과에 남긴다.

## 3. P0 — 회귀 기준선과 평가 계약

### 구현

- `bench/wiki_builder/dataset.jsonl`에 28개 회귀 사례가 있다.
- 부분 관계 누락, 온보딩 날씨 Anchor, 공동 출현 오연결 금지, canonical 병합,
  standalone 처리, stale support 대체와 degree 안정성 사례를 포함한다.
- `bench/wiki_builder/run.py`는 노드 추출 → identity → 하이브리드 후보 → Relation
  Linker → Build Plan 경로를 평가한다.
- 관계 precision·recall, unsupported edge, canonical merge, disposition,
  provenance·confidence·review 상태와 lifecycle을 채점한다.
- stale·degree 케이스는 `sync_wiki_relation_supports` 뒤의 active Head 계약을
  재현한 fingerprint 검증 Fixture를 입력받는다. Fixture가 없거나 현재 데이터셋과
  맞지 않으면 비용 계산과 LLM 호출 전에 중단한다.
- `--confirm-cost`가 없으면 실제 LLM 호출 전에 중단한다.

### 2026-08-09 실측

`gpt-4.1-mini`로 28건을 실행한 최종 결과는 20건 통과(71.43%), 관계 recall
83.33%(15/18), precision 100%(15/15), unsupported edge 0건이다. Canonical merge,
node disposition, stale edge, degree 안정성, provenance 필드는 평가 대상에서 모두
100%였다. 평균 지연은 14.517초, 입력 68,897·출력 26,072 토큰, 저장소 단가 기준
비용은 $0.069274였다. 상세 결과는
`bench/wiki_builder/results/2026-08-09_gpt-4.1-mini.md`에 보존한다.

Ontology 경계 보완 전 결과도
`bench/wiki_builder/results/2026-08-09_gpt-4.1-mini_pre-ontology.md`에 보존한다.
그 실행은 17/28, recall 63.16%, precision 92.31%였다. 다만 두 실행 사이에 기존
온보딩 후보를 신규 추출 노드처럼 채점하던 오류와 중복 추론 Edge 정답도 함께
수정했으므로, 전체 차이를 프롬프트 효과만으로 해석하지 않는다.

남은 고정 위험은 복합 기상 사례에서 `태풍 -> 날씨 / subtopic_of` 한 관계를
놓친 점과 일부 노드 추출·role 판정 실패다. 후보 점수만으로 이 Edge를 강제 생성하지
않고 실제 사용자 데이터로 recall을 계속 관측한다. 재실행에는
`bench/wiki_builder/relation_state_fixture.json`을 명시해야 한다.

## 4. P1 — 후보 회수와 별도 Relation Linker

### 후보 회수

각 신규·갱신 노드에 대해 다음 신호를 독립적으로 모으고 Top-K 후보만 Linker에 준다.

| 신호 | 역할 | Edge 자동 생성 |
|---|---|---|
| 정규화 제목·별칭 일치 | canonical 표기 후보 | 안 함 |
| token lexical·문자 trigram | 부분 표기와 설명 후보 | 안 함 |
| cosine Embedding | 문자열이 달라도 의미가 가까운 후보 | 안 함 |
| 기존 Graph 1-hop | 이미 검증된 주변 문맥 후보 | 안 함 |
| 온보딩 Anchor | 사용자가 직접 선언한 관심 주제 후보 | 안 함 |

Embedding은 `text-embedding-3-small` 1536차원 Chunk Vector를 문서 단위로 읽어
후보 순위에만 쓴다. Vector 임계값 통과는 관계의 존재를 뜻하지 않는다.

### 관계 판정

- Linker는 신규·갱신 노드 전체와 후보 노드를 한 번에 보고 관계를 판정한다.
- 모든 Edge는 신규·갱신 노드를 적어도 하나 포함해야 한다.
- `source_explicit` 0.70, `semantic_inference` 0.78, `user_declared` 0.90,
  `system_rule` 0.90의 Linker 최소 confidence 기준을 적용한다. 저장 전 WBA-014가
  같은 provenance별 하한을 다시 검증하므로 Linker와 Build Gate의 기준이 어긋나지
  않는다.
- `semantic_inference`에는 rationale가 없으면 저장하지 않는다.
- `review_status=accepted`인 관계만 자동 저장 대상으로 삼는다.
- 각 신규 노드는 `merge`, `connect`, `standalone` 중 하나와 이유를 남긴다.

### 관계 Ontology

저장소와 품질 검증기는 아래 12종을 읽는다.

| 구분 | 관계 유형 | 의미 |
|---|---|---|
| Legacy | `entity_relation` | Entity 사이의 기존 포괄 관계 |
| Legacy | `applies_concept` | Entity가 Concept를 적용·사용 |
| Legacy | `related_concept` | Concept 사이의 기존 포괄 관계 |
| Identity | `alias_of` | 같은 대상의 표기·별칭 관계 |
| Semantic | `instance_of` | 구체 Entity가 상위 Concept 유형의 인스턴스 |
| Semantic | `subtopic_of` | Concept가 더 넓은 Concept의 하위 주제 |
| Semantic | `part_of` | 대상·개념의 구성 부분 |
| Semantic | `located_in` | 장소에 위치함 |
| Semantic | `occurs_in` | 사건·현상이 장소에서 발생함 |
| Semantic | `affects` | 대상에 영향을 줌 |
| Semantic | `causes` | 원인 관계 |
| Semantic | `associated_with` | 방향을 더 구체화하지 못한 검증 관계 |

P3 검색 확장은 Identity 병합용 `alias_of`를 토픽 확장 Edge로 사용하지 않는다.
Legacy 3종과 Semantic 8종만 확장 Ontology에 포함한다.

## 5. P2 — 관계 이력, Lint와 전체 재구성

### 관계 Head와 Support 이력

`wiki_document_relations`는 현재 판정 Head다. `status`, `provenance_kind`,
`confidence`, `review_status`, model·prompt trace와 `superseded_at`을 보존한다.

`wiki_relation_supports`는 같은 관계를 지지하는 원본 Version·Build별 근거 이력이다.
같은 논리 원본의 새 Version을 Build하면 이전 active support를 `superseded`로 바꾸고,
이번 원본에서 실제 관측한 support만 멱등 upsert한다. 다른 원본의 active support가
남아 있으면 관계 Head는 유지하고, 마지막 active support가 사라질 때만 Head를
`superseded`로 바꾼다. 삭제 Cascade 뒤에도 근거 없는 active Head가 남지 않도록
DB Trigger가 같은 규칙의 안전망 역할을 한다.

### WBA-014 품질 검증

저장 전 결정적 Lint는 다음을 검사한다.

- 문서 ID·canonical 표면형 중복
- 존재하지 않는 endpoint, 자기 관계, 중복 관계와 잘못된 kind 조합
- 지원하지 않는 relation type, provenance, review·lifecycle 상태
- 낮은 confidence와 인용·출처·사용자 선언·규칙 근거가 없는 관계
- superseded·rejected 관계의 현재 Snapshot 혼입
- 검증 관계 기준 고아 문서, 모순 Metadata와 과밀 Hub

오류는 저장을 차단하고 고아 문서·일부 모순·과밀 Hub 같은 경고는 결과에 남긴다.

### WBA-002 Full Rebuild

삭제되지 않은 원본 Head의 최신 Version 전체를 온보딩 시드 우선 순서로 메모리에서
재분류한다. 따라서 시드 Concept가 뒤따르는 일반 원본의 Anchor 후보로 먼저 준비된다.
identity·Relation Linker·Lint를 기존 Wiki를 변경하지 않은 채 끝낸 뒤, 하나의 최종
Transaction에서 기존 파생 Wiki와 관계 support를 supersede하고 새 Snapshot을
저장한다. 중간 저장 실패는 Transaction rollback 대상이다. Embedding은 Wiki 교체 후
best-effort로 갱신한다.

현재 `wba_002` facade와 저장소 함수는 구현됐지만 Full Rebuild용 내부 API·Job 종류·
Worker route는 연결되지 않았다. 실제 PostgreSQL을 사용한 전체 재구성 운영 검증도
남아 있으므로 “수동 호출 가능한 구현”으로만 본다.

## 6. Degree 의미

`degree`는 화면·관심사·P3 Gate에서 의미가 다르므로 같은 숫자로 해석하면 안 된다.

| 사용처 | 정의 | 같은 두 노드 사이 관계가 여러 종류일 때 |
|---|---|---|
| Wiki Graph API/UI | active이며 rejected가 아닌 **고유 이웃 수** | 이웃 1개로 계산 |
| 관심사 구조 점수 | 고유 이웃마다 가장 강한 relation weight를 하나 선택한 뒤 합계 | 중복 가산하지 않음 |
| P3 Hub Gate | 검증 Edge 중 한 노드에 닿는 Edge 비율 | Graph 편중 차단에만 사용 |

따라서 `서울` 노드가 큰 것은 연결 Row 수나 원문 등장 횟수 자체가 아니라 현재 Graph의
서로 다른 이웃이 많다는 뜻이다. 관계 유형만 다른 동일 이웃 Edge를 추가해도 UI
노드 크기는 커지지 않는다. 이것은 PageRank나 의미 중요도 점수가 아니다.

관심사 relation weight는 `related_concept`와 `associated_with`가 0.5,
`entity_relation`·`applies_concept`와 나머지 Semantic 7종이 1.0이다. Identity용
`alias_of`는 0이라 구조 점수에 기여하지 않는다. lifecycle이 active이고 rejected가
아니며 활성 Entity·Concept를 잇는 관계만 계산한다.

## 7. P3 — Embedding 후보 검색과 Graph 성숙도 Gate

### 연결된 범위

- 변경된 Entity·Concept Chunk의 Embedding을 Incremental Build의 `embed` 노드와
  Full Rebuild 후처리에서 갱신한다(`WBA-011`).
- 다음 Incremental Build는 기존 문서 Vector와 신규 노드 Query Vector의 cosine
  유사도를 Relation Linker 후보 recall에 사용한다.
- Embedding 실패 시 비Vector 후보로 폴백하며, cosine 점수만으로 Edge를 만들지 않는다.

### 검색 경로에 연결된 Graph 확장

`graph_expansion.py`는 다음 Gate를 통과한 Graph에만 2-hop personalized PageRank를
계산하는 순수 모듈이다.

- 기본 최소 검증 Edge 3개
- verified edge 비율 0.75 이상
- 단일 Hub 편중 0.80 이하
- active·accepted·지원 근거가 있고 provenance별 confidence를 넘긴 양수 weight Edge
- Seed에서 최대 2-hop, 상위 3개 기본 반환

Gate 실패 시 검증된 직접 이웃만 반환하는 `one_hop` 또는 명시적인 `empty` 폴백을
선택한다. superseded, unsupported, rejected, 근거 없는 Edge는 순회하지 않으며 임의
Edge를 만들지 않는다.

일반 Report Builder의 실시간 수집 보조 검색어 경로는 관계 Head·endpoint 제목·active
support Snapshot을 읽어 이 Gate를 실행한다. 통과하면 bounded PPR, 실패하면 검증된
1-hop 또는 empty를 쓴다. 조직 노드는 검색어와 PPR 경로에서 제외한다. 0017 Migration
미적용 등 Snapshot 조회 자체가 실패한 경우에만 기존 active/non-rejected 1-hop SQL로
운영 호환 폴백한다. `INT-012`의 Job 고정 관심사 묶음은 재시도 결정성을 위해 접수 당시
고정한 1-hop 키워드를 계속 사용한다.

또한 `PRAG-003`의 개인 문서 검색은 여전히 FTS·키워드 결합이며 pgvector 결과를
합치는 검색은 구현되지 않았다. 이번 Vector 사용처는 Wiki **관계 후보 recall**이다.

## 8. 구현 상태 요약과 남은 작업

| 단계 | 현재 상태 | 남은 작업 |
|---|---|---|
| P0 회귀 데이터·채점기 | 28건 실측 완료, recall 83.33%·precision 100% | 실패 사례와 운영 데이터 recall 추적 |
| P1 후보 회수·Relation Linker | Incremental Build 연결·실측됨 | 복합 taxonomy 누락 관계 개선 |
| P1 온보딩 Anchor | 후속 일반 Build 연결·폭염→날씨 실측 통과 | 운영 사용자 회귀 확인 |
| P2 provenance·lifecycle | Migration·저장 동기화·로컬 DB 계약 검증 완료 | 배포 DB Migration·삭제/갱신 통합 검증 |
| P2 WBA-014 Lint | Incremental·Full Rebuild에 연결됨 | 운영 임계값 관측과 조정 |
| P2 WBA-002 Full Rebuild | facade 구현, 운영 route 미연결 | API/Job/Worker route와 DB E2E |
| P3 WBA-011 Embedding | Build 후 best-effort 연결됨 | Provider 실패 재처리 운영 경로 |
| P3 2-hop PPR Gate | 일반 Report 보조 검색어 경로 연결됨 | 실제 데이터 A/B 품질·지연 검증 |
| PRAG-003 Vector 검색 | 미구현 | 사용자 Scope Vector 검색·결합·recall 실측 |

완료 판단은 단위 테스트 통과만으로 하지 않는다. 프롬프트·모델·Graph 구조가 바뀌면
P0 벤치마크를 다시 실행하고 관계 precision·recall, unsupported-edge 비율, canonical
merge 정확도, disposition 정확도, 지연·토큰·비용을 결과 파일에 모두 기록한다.
