# Agent API MVP 개발 범위

> 이 문서는 전체 기능 명세의 고유 ID를 그대로 사용하며, MVP에서 구현할 항목만 선별한 범위 문서입니다.

## MVP 목표

- 사용자가 선택한 데이터로 Entity·Concept·Schema 구조의 개인 LLM Wiki를 구성한다.
- 웹 클리퍼가 전달한 Frontmatter와 Markdown 원문을 PostgreSQL에 영구 저장한다.
- Personal Wiki Builder Worker가 저장된 클리핑을 Chunk·Embedding·관심사 갱신까지 비동기로 처리한다.
- 개인 Wiki 데이터를 기반으로 사용자 관심사를 분류한다.
- Naver API, NewsAPI, GDELT 데이터를 정기적으로 수집한다.
- 개인 Wiki와 최신 수집 데이터를 결합해 밤비 콘텐츠를 생성한다.
- 생성 결과를 service-api 및 service-worker가 사용할 수 있도록 제공한다.
- Scheduler와 Worker가 생성 Job을 Batch로 처리하고, Service Worker가 준비된 Publish Snapshot을 Batch로 가져가 service-db에 반영한다.

## 1. Service API 연동

| ID | 기능 | 설명 |
|---|---|---|
| SVC-001 | 사용자 컨텍스트 전달 | 서비스 사용자 설정을 Agent 컨텍스트로 전달한다. |
| SVC-002 | 웹 클리핑 처리 요청 | 클리핑 Markdown을 영속 저장하고 Personal Wiki Builder Job을 등록한다. |
| SVC-003 | URL 처리 요청 | 입력된 URL을 개인 Wiki 처리 작업으로 전달한다. |
| SVC-004 | 위키마킹 처리 요청 | 사용자가 선택한 콘텐츠의 Wiki 편입을 요청한다. |
| SVC-008 | 콘텐츠 생성 요청 | 밤비의 콘텐츠 생성을 요청한다. |
| SVC-013 | Agent Job 상태 조회 | 비동기 작업 상태를 조회한다. |
| SVC-014 | Agent 결과 조회 | 생성 및 처리 결과를 Agent API에서 조회한다. |

### 웹 클리핑 수신·영속 저장

| ID | 기능 | 설명 |
|---|---|---|
| WSE-001 | 웹 클리핑 이벤트 수신 | title, source, author, published, created, description, tags와 Markdown 본문을 수신한다. |
| WSE-011 | 이벤트 중복 처리 방지 | 사용자와 source_event_id 조합으로 동일 클리핑의 중복 저장·Job 생성을 막는다. |
| WSE-013 | 이벤트 처리 상태 관리 | 클리핑의 received, processing, completed, failed 상태를 Worker 처리와 동기화한다. |
| PWIKI-006 | 개인 Wiki 문서 버전 관리 | 원본 변경 이력과 생성된 Wiki 변경 이력을 각각 Version으로 관리한다. |
| PWIKI-007 | Wiki 문서 출처 추적 | 생성된 Wiki Version과 참고한 원본 Version의 관계를 보존한다. |
| PWIKI-011 | Wiki 문서 정규화 | Frontmatter와 Markdown 원본을 읽어 LLM Wiki 문서 구조로 변환한다. |
| DB-002 | Wiki Source Event·원본 저장 | 요청 상태는 wiki_source_events에, Frontmatter와 Markdown은 user_source_documents 계열에 영속 저장한다. |
| DB-003 | 개인 LLM Wiki 문서 저장 | Worker가 만든 Entity·Concept·Schema를 wiki_documents·wiki_document_versions에 저장하고 원본·문서 관계를 연결한다. |

클리핑 API는 DB Transaction이 Commit된 뒤에만 202 Accepted를 반환합니다. Agent API가
Markdown 저장에 실패했는데 Job만 접수하거나, 인메모리에만 저장한 상태로 성공을
반환하는 구현은 MVP 완료로 보지 않습니다.

## 2. 사용자 개인 LLM Wiki

| ID | 기능 | 설명 |
|---|---|---|
| PWIKI-002 | 개인 Wiki 문서 생성 | 사용자가 선택한 데이터를 Wiki 문서로 변환한다. |
| PWIKI-003 | 개인 Wiki 문서 조회 | 사용자의 Wiki 문서 목록과 상세 내용을 조회한다. |
| PWIKI-005 | 개인 Wiki 문서 삭제 | 사용자가 제거한 데이터를 Wiki 검색 대상에서 제외한다. |
| PWIKI-008 | Wiki 문서 중복 제거 | 동일하거나 유사한 개인 Wiki 문서를 중복 제거한다. |
| PWE-001 | 개인 Wiki 문서 Chunking | Wiki 문서를 의미 단위 Chunk로 분할한다. |
| PWE-002 | Chunk 저장 | 생성된 Chunk를 문서 Version과 연결해 PostgreSQL에 저장한다. |
| PWE-004 | Embedding 생성 | 개인 Wiki Chunk의 Vector를 생성한다. |
| PWE-005 | Embedding 저장 | 사용자별 Vector 검색 저장소에 Embedding을 저장한다. |
| PRAG-003 | Hybrid Search | Keyword와 Vector 검색 결과를 결합한다. |
| PRAG-006 | 개인 Wiki Context 구성 | LLM 입력에 사용할 개인 Wiki Context를 구성한다. |
| PRAG-007 | Citation 연결 | 생성 결과와 참조한 개인 Wiki 문서를 연결한다. |

### 개인 Wiki Graph 조회

- `PWIKI-003`은 현재 Entity·Concept 문서 Version과 `wiki_document_relations`를
  Node·Edge Graph로 조회합니다.
- Graph 응답은 사용자 Namespace의 문서만 포함하고 PostgreSQL RLS 사용자 Scope를
  함께 적용합니다.
- 내부 데이터 API는 `GET /internal/v1/users/{user_id}/wiki/graph`, 시각화 페이지는
  `GET /wiki-graph?user_id={user_id}`로 제공합니다.
- 페이지는 검색, Entity·Concept 필터, 확대·축소·이동·Node Drag와 Markdown 상세
  보기를 제공하며 별도의 브라우저 저장소를 지식 원본으로 사용하지 않습니다.

### Obsidian LLM Wiki 구조 계약

- Entity는 입력에서 발견한 고유 대상별로 `entities/{document_key}.md` 한 개를 유지합니다.
- 같은 `document_key`의 Entity가 이미 있으면 새 문서를 만들지 않고 기존 `wiki_documents`에 새 `wiki_document_versions`를 추가합니다.
- Concept은 둘 이상 Entity에서 반복되는 설계 패턴일 때만 `concepts/{document_key}.md`로 생성합니다. 단일 Entity 전용 설명은 Entity 문서에 남깁니다.
- 기존 Concept과 70% 이상 겹치는 패턴은 새 문서로 만들지 않고 기존 Concept을 갱신합니다. 의미 유사도는 Worker가 판단하고 DB는 결과만 보존합니다.
- Schema는 사용자 Namespace당 `schema/schema.md` 하나만 존재하며, Entity 추가·삭제나 관계 변경 시 새 Version을 생성합니다.
- 완성 Markdown은 YAML Frontmatter를 포함해 `wiki_document_versions.normalized_content`에 저장합니다.
- `wiki_document_relations`는 Entity·Concept 관계를, `wiki_version_documents`는 특정 Wiki Build의 문서 Version·파일 경로 구성을 보존합니다.

## 3. DB 기반 관심사 분류

| ID | 기능 | 설명 |
|---|---|---|
| INT-001 | 관심사 Topic 추출 | 개인 Wiki와 사용자 행동에서 관심 주제를 추출한다. |
| INT-002 | 관심사 Category 분류 | 관심사를 서비스의 분류 체계에 매핑한다. |
| INT-005 | 관심사 점수 계산 | 사용자 행동 강도와 최신성을 기반으로 점수를 계산한다. |
| INT-011 | 관심사 프로필 재계산 | Wiki 변경 시 관심사 구조와 점수를 다시 계산한다. |

## 4. 외부 데이터 자동 수집

| ID | 기능 | 설명 |
|---|---|---|
| COL-002 | Naver API 수집 | 설정된 키워드로 Naver API 데이터를 수집한다. |
| COL-003 | GDELT 수집 | 글로벌 뉴스와 이벤트 데이터를 수집한다. |
| COL-004 | NewsAPI 수집 | 뉴스 기사와 관련 메타데이터를 수집한다. |
| GSP-004 | API 응답 정규화 | Source별 응답을 공통 문서 구조로 변환한다. |
| GSP-006 | 문서 중복 제거 | 동일 URL과 유사 문서를 중복 제거한다. |
| GSP-015 | 개인 Wiki 자동 반영 금지 | 수집 데이터를 사용자 선택 없이 개인 Wiki에 반영하지 않는다. |
| SCH-002 | Naver API 수집 스케줄 | Naver API 수집 작업을 정기 등록한다. |
| SCH-003 | GDELT 수집 스케줄 | GDELT 수집 작업을 정기 등록한다. |
| SCH-004 | NewsAPI 수집 스케줄 | NewsAPI 수집 작업을 정기 등록한다. |

## 5. 콘텐츠 생성 에이전트 밤비

| ID | 기능 | 설명 |
|---|---|---|
| BAMBI-001 | 콘텐츠 생성 요청 | 사용자와 주제에 맞는 콘텐츠 생성 요청을 처리한다. |
| BAMBI-004 | 개인 Wiki 검색 | 사용자의 관심사와 기존 지식을 검색한다. |
| BAMBI-005 | Global Source 검색 | 최신 외부 자료와 근거를 검색한다. |
| BAMBI-008 | 콘텐츠 요약 생성 | 피드와 미리보기에 사용할 요약을 생성한다. |
| BAMBI-009 | 콘텐츠 본문 생성 | 플랜과 유형에 맞는 본문을 생성한다. |
| BAMBI-011 | 콘텐츠 Citation 생성 | 본문 주장과 참조한 자료를 연결한다. |
| BAMBI-012 | 사용자 개인화 적용 | 관심사, 언어, 비선호 설정을 반영한다. |
| BAMBI-018 | 생성 콘텐츠 후보 저장 | 발행 전 콘텐츠를 agent-db에 저장한다. |
| BAMBI-020 | 콘텐츠 완료 이벤트 | 생성 완료 사실을 Integration Event로 발행한다. |
| BAMBI-021 | 자동 Wiki 편입 금지 | 생성된 콘텐츠를 사용자 선택 없이 개인 Wiki에 넣지 않는다. |

## 6. Worker 및 서비스 반영

| ID | 기능 | 설명 |
|---|---|---|
| WORKER-001 | Global Source Collector Worker | 외부 데이터를 수집하고 Global Source Pool에 저장한다. |
| WORKER-002 | Personal Wiki Builder Worker | 사용자 선택 데이터를 개인 Wiki로 구성한다. |
| WORKER-003 | Bambi Generation Worker | 생성 Job Batch를 점유하고 제한된 동시성으로 개인화 콘텐츠를 생성한다. |
| SW-001 | Content Ready 이벤트 수신 | 발행 가능한 콘텐츠 이벤트를 소비한다. |
| SW-004 | Publish Snapshot 조회 | Agent API에서 단건 Snapshot을 조회하거나 준비된 Snapshot Batch를 Claim한다. |
| SW-007 | service-db 콘텐츠 Upsert | Batch의 각 콘텐츠 발행본을 멱등하게 저장하거나 갱신한다. |
| SW-009 | 발행 완료 ACK | 단건 또는 Batch의 항목별 service-db 반영 결과를 Agent API에 알린다. |

### Personal Wiki Builder Worker 구현 범위

| ID | 기능 | 설명 |
|---|---|---|
| WBA-001 | Incremental Wiki Build | 새로 저장된 사용자 원본 Version만 증분 처리한다. |
| WBA-003 | Wiki 문서 정규화 | 저장된 Markdown과 Metadata를 Chunking 가능한 공통 구조로 정리한다. |
| JOB-001 | Agent Job 생성 | 클리핑 저장 Transaction에서 Personal Wiki Build Job을 함께 생성한다. |
| JOB-002 | Agent Job 조회 | API와 Worker가 클리핑 Job 상태와 진행률을 조회한다. |
| JOB-006 | Agent Job 진행률 관리 | 정규화, Chunking, Embedding, 관심사 갱신 단계를 기록한다. |
| JOB-007 | Agent Job 결과 연결 | 입력에는 원본 ID를, 완료 결과에는 생성·갱신된 문서/Version ID 목록과 wiki_version_id를 연결한다. |
| JOB-010 | Agent Job Idempotency | 동일 클리핑 요청이 Worker Job을 중복 생성하지 않도록 한다. |
| WC-001 | Queue Job Consume | Worker가 실행 가능한 Personal Wiki Job Batch를 가져온다. |
| WC-002 | Job Claim | FOR UPDATE SKIP LOCKED와 Lease로 Job Batch를 점유한다. |
| WC-006 | Retry 정책 | 재시도 가능한 Chunking·Embedding 실패를 Backoff 후 다시 처리한다. |
| WC-009 | Idempotency 처리 | 같은 원본을 다시 처리해도 document_kind+document_key, Wiki·출처·관계·Snapshot Row가 중복되지 않게 한다. |
| WC-013 | Concurrency 제어 | Claim 크기와 Embedding 동시 실행 수를 별도로 제한한다. |
| DB-004 | 개인 Wiki Chunk 저장 | wiki_chunks에 문서 Version별 Chunk를 영속 저장한다. |
| DB-005 | 개인 Wiki Embedding 저장 | wiki_embeddings에 Chunk별 Vector를 영속 저장한다. |
| DB-026 | Agent Job 저장 | agent_jobs와 agent_job_attempts에 Claim, Lease, 상태와 시도 이력을 저장한다. |

### 웹 클리핑 Worker 완료 계약

- Extension은 service-api의 사용자 인증 경계를 거치고, service-api가 Agent API의 내부 클리핑 경로를 호출합니다.
- Agent API는 source_event_id 멱등성을 확인한 뒤 Source Event, 사용자 원본 문서·Version, Personal Wiki Build Job을 한 Transaction으로 저장합니다.
- Markdown 원문 저장은 LLM 호출 없이 수행하며 title과 본문은 각각 user_source_document_versions.title, raw_content에 보존합니다.
- Worker는 Job Batch를 Lease와 함께 Claim하고 source_document_version_id를 기준으로 Entity·Concept·Schema를 Upsert합니다. 새 문서 Version, 원본·문서 관계, Wiki Build 구성을 한 결과 Transaction에 저장한 뒤 Chunk, Embedding과 관심사를 갱신합니다.
- Worker 재시도 중에도 Markdown 원문과 Frontmatter는 삭제하지 않습니다. 생성 Wiki·출처 관계·Chunk·Embedding만 멱등하게 다시 생성할 수 있습니다.
- 성공 시 Source Event와 Job을 completed로 바꾸고 source_document_id, source_document_version_id, wiki_version_id, affected_documents, chunk_count를 결과에 기록합니다. affected_documents의 각 항목은 document_id, document_version_id, document_kind, document_key, file_path를 포함합니다.
- 최종 실패 시 Source Event와 Job의 오류를 기록하되 저장된 Markdown 원문은 사용자가 삭제할 때까지 유지합니다.

### MVP Batch 처리 계약

- 콘텐츠 생성 트리거는 service 계층 스케줄러가 담당한다(2026-07-20 결정). 사용자 지정 생성 시간의 원천 데이터가 service-db에 있으므로, service 스케줄러가 `schedule window + user_id + content_type` 규칙의 `idempotency_key`로 `POST /generations`를 호출하고, 미리 등록할 때는 `scheduled_at`으로 실행 시각을 예약한다. Agent는 별도의 생성 Scheduler를 두지 않는다(구 SCH-011 제거).
- Agent Worker는 한 트랜잭션에서 실행 가능한 Job 여러 건을 `FOR UPDATE SKIP LOCKED`로 Claim하고, DB Transaction 밖에서 제한된 동시성으로 각 Job을 독립 실행한다.
- Batch Claim 크기와 실제 LLM 호출 동시성은 별도 설정으로 관리한다. 한 Batch를 하나의 LLM 요청으로 합치지 않는다.
- 각 Job은 독립적으로 완료·재시도·실패 처리하며, 생성 후보·Publish Snapshot·Outbox Event를 같은 저장 경계에서 기록한다.
- Spring 계층에서는 HTTP 요청을 처리하는 service-api가 아니라 별도 Service Worker/Scheduler가 Agent API의 Publish Snapshot Batch를 Claim한다. 같은 배포 바이너리를 사용하더라도 실행 역할과 분산 Lock을 분리한다.
- Publish Snapshot Batch 응답은 추가 단건 조회 없이 service-db에 반영할 수 있도록 전체 Snapshot Payload를 포함한다.
- Service Worker는 `content_id + version`으로 service-db에 멱등 Upsert한 뒤, 성공과 실패를 항목별로 모아 부분 성공 Batch ACK한다. 전체 Batch를 하나의 service-db Transaction으로 묶지 않는다.
- ACK되지 않은 항목은 Lease 만료 후 다시 Claim할 수 있고, 재시도 가능 실패는 Backoff 후 `ready`로 돌아가며 최종 실패는 `failed`로 격리한다.
- `CONTENT_READY` 이벤트는 Batch Poll을 즉시 깨우는 신호로 사용하고, 주기적인 Batch Poll을 이벤트 유실과 Backfill의 복구 경로로 유지한다.
- 기존 단건 Snapshot 조회·ACK는 관리자 수동 복구, 장애 조사와 개별 재발행을 위해 유지한다.

## MVP 제외 범위

- 내부 서버 인증 및 세부 권한
- 자체 API Key와 External Agent API
- MCP Server
- 번역 및 이미지 생성
- 별도의 추천 Agent
- 고급 관심사 Graph
- Personal Wiki 전체 재구성 및 Memory 압축
- 다중 평가 Agent와 고급 사실 검증
- Prompt 및 추천 A/B Test
- 고급 메시징 패턴과 자동 확장

## ID 관리 원칙

- 기능 ID는 전체 기능 명세에서만 생성한다.
- MVP 문서는 전체 기능 ID 중 구현 대상을 선별해 참조한다.
- MVP 이후 기능을 구현할 때도 기존 기능 ID를 그대로 사용한다.
- 여러 기능을 개발 작업으로 묶을 때만 별도의 Epic 또는 Milestone ID를 사용한다.
