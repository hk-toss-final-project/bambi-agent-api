# PostgreSQL 기반 OpenAI 대량 처리 설계

> 승인: 2026-08-11
> 범위: `WC-007`, `WC-013`, `WC-014`, `WORKER-002`, `WORKER-003`,
> `WBA-011`, `LLM-015`, `LLM-016`, `DB-026`, `DB-029`

## 1. 결정

OpenAI 호출 제어를 위해 Redis를 도입하지 않는다. 기존 PostgreSQL
`agent_jobs`를 작업의 원천으로 유지하고 다음 세 경계를 추가한다.

1. Worker는 Batch Claim 크기와 실제 Job 동시 실행 수를 분리한다.
2. 동기 OpenAI 호출은 PostgreSQL Provider Rate Governor를 거친다.
3. 즉시 결과가 필요 없는 작업은 OpenAI Batch API 상태를 PostgreSQL에
   영속화하고 별도 Worker가 제출·조회·결과 반영한다.

PostgreSQL Transaction이나 Row Lock을 잡은 상태로 외부 API 응답을 기다리지
않는다. Claim, Rate 예약, Batch 상태 변경과 결과 반영은 각각 짧은
Transaction으로 끝낸다.

## 2. 동기 호출 경계

### Worker 동시성

- `*_WORKER_BATCH_SIZE`는 한 번에 Claim할 최대 Job 수다.
- `*_JOB_CONCURRENCY`는 Claim한 Job을 동시에 실행할 최대 수다.
- Job마다 Connection Pool에서 독립된 연결을 빌린다. 하나의
  `AsyncConnection`을 동시 Task가 공유하지 않는다.
- 기본 동시성은 1로 두고 운영 지표를 보며 올린다.

### 429 재시도

- SDK 내부 재시도와 애플리케이션 재시도를 중첩하지 않는다.
- 임시 Rate Limit은 `Retry-After`를 최소 대기시간으로 사용하고 jitter를 더한다.
- 헤더가 없거나 잘못됐으면 지수 Backoff와 jitter를 사용한다.
- 최대 시도 횟수와 총 대기시간을 제한한다.
- quota, billing처럼 사용자 조치가 필요한 429는 재시도하지 않는다.
- Worker Job 재시도는 LLM 호출 내부 재시도가 끝난 뒤에만 적용한다.

### PostgreSQL Provider Rate Governor

Provider와 모델별로 다음 상태를 저장한다.

- 요청·Token 상한과 잔여량
- 요청·Token Reset 시각
- 429의 `Retry-After`를 반영한 `blocked_until`
- 마지막 OpenAI `x-request-id`

Worker는 Job 실행 전에 예상 요청 수와 Token을 원자적으로 예약한다. 잔여량이
부족하면 DB Lock을 해제한 뒤 Reset 시각까지 기다리고 다시 예약한다. 성공·실패
응답의 `x-ratelimit-*` 헤더는 다음 예약 판단에 반영한다. 실제 상한을 아직
관찰하지 못한 초기 상태에서는 환경변수의 보수적 RPM/TPM을 사용한다.

## 3. OpenAI Batch 상태 모델

### 로컬 Batch

`llm_batches`는 OpenAI Batch 하나를 나타낸다.

- 같은 Batch에는 Provider, endpoint, model, workload가 같은 요청만 포함한다.
- 상태는 `preparing → submitted → in_progress → completed` 순서로 진행한다.
- Provider의 `failed`, `expired`, `cancelled`도 그대로 보존한다.
- `input_file_id`, `provider_batch_id`, `output_file_id`, `error_file_id`를 저장한다.
- Poll 실패는 Batch 실패로 단정하지 않고 `next_poll_at`을 Backoff한다.

### Batch Item

`llm_batch_items`는 입력 JSONL 한 줄과 결과 한 줄을 나타낸다.

- `custom_id`는 전역 Unique이며 결과 순서와 무관하게 Item을 찾는 기준이다.
- 요청 Body, 대상 Resource, 결과 Body, Error와 Token 사용량을 보존한다.
- 같은 Item 결과를 여러 번 반영해도 도메인 저장 결과가 중복되지 않아야 한다.
- 완료 Batch의 output과 error 파일을 모두 읽어 부분 성공을 반영한다.
- `expired` Batch의 완료 Item은 유지하고 미완료 Item만 새 Batch 대상으로 되돌린다.

한 번에 최대 500 Item으로 시작한다. OpenAI의 단일 Batch 제한보다 충분히 낮게
두고, 운영 계정의 모델별 queued token limit을 확인한 뒤 조정한다.

## 4. Wiki 처리

### 증분 Build

분류, identity 해소, 관계 판정은 현재 Wiki Head에 의존하므로 동기 API를 유지한다.
서로 다른 사용자의 Job은 제한된 동시성으로 실행하되 동일 사용자의 Wiki Job은
직렬화한다.

### Embedding

- 변경 Chunk가 설정된 임계값보다 적으면 동기 Embedding을 사용한다.
- 임계값 이상이면 `/v1/embeddings` Batch Item으로 등록하고 Wiki Build는 완료한다.
- Item은 Chunk ID와 입력 순서를 함께 저장한다.
- 결과 Vector 수·차원을 검증한 뒤 `wiki_embeddings`에 멱등 Upsert한다.
- 실패·만료 Item만 다시 등록하고 이미 저장된 Vector는 재생성하지 않는다.

### Full Rebuild

현재 Full Rebuild는 앞 원본의 분류 결과를 다음 원본의 canonical 후보로 사용하는
순차 의미와 최종 원자적 교체 계약을 유지한다. 이번 범위에서는 분류 전체를
OpenAI Batch로 바꾸지 않고, 교체 후 대량 Embedding만 Batch로 보낸다. 분류를
추출 Wave와 전역 병합 Wave로 나누는 변경은 별도 품질 Benchmark와 함께 진행한다.

## 5. Report 처리

- 즉시 생성, welcome, 정시성이 중요한 예약 Report, Researcher·Critic·변경점
  추적은 동기 API를 유지한다.
- 명시적으로 비긴급 Batch 실행을 요청한 backfill·대량 재생성만 초안 생성을
  `/v1/chat/completions` Batch로 보낸다.
- Research와 Context 고정은 먼저 수행하고, 생성 Prompt와 Context Snapshot을
  Item Metadata에 저장한다.
- Batch 결과는 허용 Citation, JSON 구조와 무료 품질 규칙을 검증한다.
- 품질 미달 또는 Critic 재작성 요청은 최대 한 번 동기 API로 교정한다.
- 결과 저장은 기존 Citation, 생성 후보, Publish Snapshot, Outbox 경계를 재사용한다.

Batch 대기 중 Agent Job은 `waiting_provider`이며 Worker Lease를 점유하지 않는다.
결과 반영이 끝나면 기존 `completed` 계약으로 전환한다.

## 6. 운영과 검증

최소 관측 항목은 다음과 같다.

- 작업 유형별 Claim 수, 실행 동시성, 대기시간
- 모델별 예약·실제 Token, 잔여 RPM/TPM, Reset·차단 시각
- 429 횟수, 내부 재시도 횟수, Job 재시도 횟수
- Batch Item 성공·실패·만료 수, 제출부터 완료까지 지연
- 동기 대비 Batch 비용과 Wiki Embedding·Report 품질 회귀

단위 테스트는 실제 OpenAI 호출 없이 Provider를 대체한다. 실제 LLM 품질
Benchmark는 `bench/`에 Wiki와 Report를 분리해 두고, 실행 전 예상 비용 승인을
받는다.
