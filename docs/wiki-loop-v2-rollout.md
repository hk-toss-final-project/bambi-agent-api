# Wiki 읽기·유지 루프 V2 전환 계약

> 승인 기준일: 2026-08-11
>
> 범위: Report Builder의 Wiki 읽기 루프와 Personal Wiki 정기 유지 루프
>
> 제외: Wiki 쓰기(증분 Build) 루프

## 1. 목표

기존 구현은 삭제하거나 제자리에서 교체하지 않는다. 같은 배포 안에 V1과 V2를
함께 두고, Job을 등록할 때 선택한 실행 버전을 Payload에 고정한다. Worker는 현재
환경설정이 아니라 Job Payload의 버전을 실행하므로 배포 중 기본값이 바뀌어도 이미
접수된 Job의 의미와 재시도 결과가 달라지지 않는다.

읽기 루프는 V1·V2를 사용하고, 유지 루프는 호환 V3를 추가로 허용한다.

| 값 | 의미 |
|---|---|
| `legacy_v1` | 기존 Python/Researcher 실행 경로 |
| `langgraph_v2` | 명시적인 LangGraph 상태·노드 실행 경로 |
| `langgraph_v3` | 유지 전용 의미 감사·수리·외부 수집·내부 재구성 그래프 |

버전 필드가 없는 과거 Job은 반드시 `legacy_v1`로 해석한다. 운영 롤백은 환경변수의
기본값을 `legacy_v1`로 되돌려 새 Job부터 V1로 접수하는 방식이며, 실행 중인 Job의
버전은 바꾸지 않는다.

## 2. 읽기 루프 계약

환경변수 `WIKI_READ_PIPELINE_VERSION`이 새 Report Job의
`read_pipeline_version`을 결정한다. 접수 시점의 활성 `wiki_version_id`, 관심사
묶음과 Topic별 Navigation Snapshot 고정 계약은 그대로 유지한다.

```text
legacy_v1
  Researcher Tool Loop → Global 충분성 판정 → 필요 시 Live 수집

langgraph_v2
  Snapshot 복원 또는 Locate
  → 결정적 Seed 선택·Navigation
  → Global 저장 근거 조회
  → 충분성 판정
  → 필요 시 Live 수집 1회
  → Context·Trace 조립과 Snapshot 저장
```

V2도 Navigator의 책임 경계를 바꾸지 않는다. Navigator는 Page·관계·Source가 담긴
Context Packet만 반환하고, 최종 리포트 추론과 작성은 Report Builder가 담당한다.
후보 선택은 exact/alias/RRF 순서의 결정적 정책을 사용해 V1의 반복적인 Tool LLM
왕복을 제거한다.

여러 주제를 묶은 리포트는 하나의 DB 연결에서 Topic별 Wiki·Global 조회와 판정을
짧게 끝낸 뒤, 저장 근거가 부족한 Topic의 Live 수집만 최대 3개까지 병렬 실행한다.
Topic별 결과는 원래 입력 순서로 다시 조립하며, 문서 중복은 Topic마다 다시 매겨지는
참조 번호가 아니라 원본 Version·Chunk 식별자로 제거한다.

## 3. 유지 루프 계약

환경변수 `WIKI_MAINTENANCE_PIPELINE_VERSION`이 새 Full Rebuild Job의
`maintenance_pipeline_version`을 결정한다. 원본 제거 Job과 Scheduler 정기 Job
모두 같은 규칙으로 버전을 고정한다.

```text
legacy_v1
  활성 원본 조회 → 전체 재분류 → Lint → 원자 교체 → Embedding

langgraph_v2
  Audit → Plan
    ├─ noop → 결과 기록
    ├─ repair_derivatives → 누락 Embedding 복구
    └─ full_rebuild → 검증된 V1 원자 교체 실행기 재사용
  → Finalize

langgraph_v3
  운영 감사 → 현재 구조 Lint → 전역 후보·LLM 의미 감사
  → 누락 Page·관계 원자 수리 → 외부 공백 URL 수집 Job 등록
  → Embedding·관심사 후처리 → 감사 지표 저장
```

V2는 이미 검증된 Full Rebuild 저장 알고리즘을 복제하지 않는다. 구조 재구성이
필요한 경우 V1 실행기를 어댑터로 호출해 순차 분류 의미, 저장 전 Lint, 최종 단일
Transaction 교체를 그대로 보존한다. 건강한 Wiki는 `noop`, 구조는 건강하지만
Embedding만 빠진 Wiki는 `repair_derivatives`로 끝내 불필요한 전체 LLM 재분류를
줄인다.

V3의 상세 문제 코드·비용 상한·외부 쓰기 경계·롤백 계약은
`docs/wiki-maintenance-v3.md`를 따른다. 초기 기본값은 V2를 유지하고 명시적으로
선택한 V3 Job만 canary 실행한다.

## 4. 공통 신뢰성 계약

- 긴 LLM 처리 중 Worker는 Claim Lease를 주기적으로 연장한다.
- Job Payload 누락처럼 명시적인 입력 오류만 영구 실패로 분류한다.
- 모델 출력 파싱 오류를 포함한 그 밖의 실행 오류는 재시도 정책을 적용한다.
- Scheduler는 Job 등록만 담당하며 LangGraph 안에 상주 sleep 루프를 넣지 않는다.
- 원문·Secret은 Trace나 Job 결과에 저장하지 않는다.

## 5. 출시 순서

1. V2를 새 Job의 기본값으로 사용하고 결정적 테스트를 통과한다.
2. 동일한 입력의 V1 기준선과 지연, 근거 수, Live 수집률과 실패율을 비교한다.
3. 문제 발생 시 기본값을 V1으로 되돌린다. 진행 중 Job은 고정 버전으로 마친다.

Reader 또는 Graph 구조를 바꾸면 `bench/wiki_navigation/` 평가를 갱신한다. 실제
Provider를 호출하는 벤치마크는 케이스 수와 예상 Token·비용을 먼저 고지한 뒤에만
실행한다.
