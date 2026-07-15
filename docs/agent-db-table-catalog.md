# Agent DB 테이블 카탈로그

> 기준: 2026-07-15. 물리 스키마의 최종 기준은
> database/migrations/0001_initial.sql,
> database/migrations/0002_publish_snapshot_batches.sql,
> database/migrations/0003_web_clipping_markdown.sql,
> database/migrations/0004_separate_user_sources_from_llm_wiki.sql입니다.

이 문서는 Agent DB의 41개 테이블을 영역과 데이터 성격으로 분류하고, 각 테이블의
책임, 핵심 관계·제약, RLS 적용 여부와 현재 애플리케이션 연결 상태를 정리합니다.
데이터 소유권, 배포 구조와 운영 원칙은 agent-db-design.md를 함께 참고합니다.
컬럼별 타입·필수 여부·기본값·의미는 agent-db-column-dictionary.md를 참고합니다.

## 1. 공통 기준

- 모든 애플리케이션 테이블은 PostgreSQL의 agent Schema에 있습니다.
- Agent가 생성하는 내부 식별자는 UUID를 사용합니다.
- user_id, content_id 등 Service가 소유하는 경계 식별자는 text로 저장하고
  service-db와 Foreign Key를 만들지 않습니다.
- 설정, 사용자 컨텍스트, Wiki, 관심사와 생성 콘텐츠는 현재 값을 덮어쓰기보다
  새 Version Row를 추가하는 방식을 우선합니다.
- 개인 데이터 테이블은 user_id 또는 namespace_key를 기준으로 RLS를 적용합니다.
- Global 지식은 namespace_key = global로 저장하며 읽기는 허용하고 쓰기는
  System Scope에 한정합니다.
- JSONB는 Provider별 확장 Metadata와 정책 설정에 사용하되, 조회와 무결성에
  중요한 값은 명시적인 Column과 제약으로 관리합니다.

### 테이블 성격

| 성격 | 의미 |
|---|---|
| Master | Source, Prompt 등 안정적인 식별자를 가진 기준 정보 |
| Version | 변경 시 기존 Row를 보존하고 새 Version을 추가하는 불변 이력 |
| Snapshot | 특정 시점의 사용자·발행 상태를 고정한 데이터 |
| Operational | Queue, Job, Claim처럼 처리 과정에서 상태가 변경되는 데이터 |
| History | Attempt, Usage, Audit처럼 실행 결과를 누적하는 데이터 |
| Derived | Chunk, Embedding, Trend처럼 원본에서 다시 만들 수 있는 파생 데이터 |
| Relation | Entity 사이의 다대다 또는 근거 연결을 표현하는 데이터 |

### 현재 런타임 연결 상태

| 표시 | 의미 |
|---|---|
| PostgreSQL 연결 | 애플리케이션 Repository가 실제 조회·저장을 수행 |
| 참조 조회 | 다른 저장 동작의 무결성 검증을 위해 읽기만 수행 |
| 인메모리 대체 | 테이블은 있으나 현재 API가 Process Memory를 사용 |
| Schema only | Migration만 존재하고 Repository·Worker는 아직 스캐폴드 |

현재 PostgreSQL Repository가 완전히 연결된 영역은 publish_snapshots와
publish_attempts입니다. generated_content_candidates는 Snapshot 저장 전
검증을 위한 참조 조회에 사용합니다. 사용자 Context와 Job API는 각각
user_context_snapshots와 agent_jobs 대신 인메모리 저장소를 사용합니다.

## 2. Migration으로 생성되는 테이블

| 영역 | 테이블 |
|---|---|
| 설정 | prompt_templates, prompt_versions, model_configs, retrieval_configs, embedding_configs |
| 사용자·Job | user_context_snapshots, agent_jobs, agent_job_attempts |
| 사용자 원본 | wiki_source_events, user_source_documents, user_source_document_versions |
| 지식 문서·검색 공용 | wiki_documents, wiki_document_versions, wiki_document_sources, wiki_chunks, wiki_embeddings |
| Personal Wiki | wiki_versions |
| 사용자 관심사 | user_interest_profiles, user_interests, interest_evidence |
| Global Source·Discovery | global_sources, global_collection_runs, global_trends, global_trend_documents, discovery_candidates |
| 콘텐츠 생성 | generation_requests, generation_runs, generated_content_candidates, citations, content_assets |
| 평가·추천 | quality_evaluations, safety_evaluations, recommendation_candidates |
| 발행 | publish_snapshots, publish_attempts |
| 이벤트·보안·운영 | event_outbox, event_inbox, api_keys, usage_logs, audit_logs |
| Migration 관리 | schema_migrations |

0001_initial.sql이 기본 38개 테이블과 Index, RLS Policy, Trigger를 생성합니다.
0002_publish_snapshot_batches.sql은 새 테이블을 만들지 않고 agent_jobs,
publish_snapshots, publish_attempts에 Lease 기반 Batch 처리 Column과 Index를
추가합니다. 0003은 과거 Wiki Version에 클리핑 필드를 추가하고, 0004는 해당 필드를
사용자 원본 테이블로 이관하면서 원본·LLM Wiki·출처 관계 테이블 3개를 추가합니다.

## 3. 설정

설정 테이블은 Runtime 코드와 분리된 Versioned Configuration입니다. 활성 버전은
Partial Unique Index로 한 개만 유지합니다.

| 테이블 | 성격 | 책임 | 핵심 관계·제약 | RLS | 현재 연결 |
|---|---|---|---|---|---|
| prompt_templates | Master | 작업별 Prompt의 안정적인 식별자와 상태 관리 | prompt_key Unique, 상태 active/inactive/deleted | 없음 | Schema only |
| prompt_versions | Version | System/User Prompt와 입출력 Schema의 불변 버전 | template_id FK, template_id + version Unique, Template별 active 1개 | 없음 | Schema only |
| model_configs | Version | Provider, Model, Parameter, Fallback과 단가 관리 | config_key + version Unique, config_key + plan별 active 1개 | 없음 | Schema only |
| retrieval_configs | Version | Keyword/Vector 가중치, Top-K, Reranking과 Citation 정책 관리 | config_key + version Unique, 가중치 0~1, plan별 active 1개 | 없음 | Schema only |
| embedding_configs | Version | Embedding Provider, Model, 차원과 Chunk 정책 버전 관리 | config_key + version Unique, 현재 dimensions = 1536 고정, config별 active 1개 | 없음 | Schema only |

## 4. 사용자 Context와 Agent Job

| 테이블 | 성격 | 책임 | 핵심 관계·제약 | RLS | 현재 연결 |
|---|---|---|---|---|---|
| user_context_snapshots | Snapshot/Version | AI에 필요한 최소 사용자 설정을 버전별 보존 | user_id + context_version Unique, plan free/paid, Soft Delete | 적용 | 인메모리 대체 |
| agent_jobs | Operational | API·Scheduler·Worker가 공유할 비동기 작업 상태 | feature_id + user_id + idempotency_key Unique, Retry/Progress/Result, Lease | 적용 | 인메모리 대체 |
| agent_job_attempts | History | Job의 Worker별 실행 시도와 오류 이력 | job_id FK Cascade, job_id + attempt_number Unique | 적용 | Schema only |

agent_jobs는 0002 Migration에서 lease_expires_at과 Claim 가능 Job 조회 Index가
추가됩니다. Claim Batch 크기와 실제 LLM 동시성은 애플리케이션 계층에서 별도로
제어해야 합니다.

## 5. 지식 문서와 검색

아래 다섯 테이블은 Agent가 구성한 Personal LLM Wiki와 정규화된 Global 지식이
공유합니다. knowledge_scope와 namespace_key가 데이터 경계를 결정합니다.

| 테이블 | 성격 | 책임 | 핵심 관계·제약 | RLS | 현재 연결 |
|---|---|---|---|---|---|
| wiki_documents | Master/Head | Agent가 생성한 Wiki 문서의 Scope, 최신 버전, URL, Hash와 상태 관리 | Personal은 user/{user_id}, Global은 global, Namespace 내 URL·Hash Unique | 적용 | Schema only |
| wiki_document_versions | Version | LLM이 구성한 제목, 요약, 정규화 본문과 생성 Job 보존 | document_id + version Unique, normalized_content 또는 object_uri 필수 | 적용 | Schema only |
| wiki_document_sources | Relation | 생성된 Wiki Version과 참고한 사용자 원본 Version 연결 | Wiki Version + 원본 Version Composite PK, 동일 Namespace FK | 적용 | Schema only |
| wiki_chunks | Derived | 문서 버전을 검색·LLM 입력 단위로 분할 | document_version_id + chunk_index Unique, FTS와 pg_trgm GIN Index | 적용 | Schema only |
| wiki_embeddings | Derived | Chunk의 의미 검색 Vector와 생성 설정 보존 | chunk_id + embedding_config_id Unique, vector(1536), Cosine HNSW | 적용 | Schema only |

wiki_document_versions.normalized_content는 클리핑 원문이 아니라 Worker가 원본을
정리·통합해 만든 LLM Wiki 본문입니다. wiki_chunks와 wiki_embeddings도 이 Wiki
결과에서 다시 만들 수 있는 검색 파생 데이터입니다.

## 6. Personal Wiki

| 테이블 | 성격 | 책임 | 핵심 관계·제약 | RLS | 현재 연결 |
|---|---|---|---|---|---|
| wiki_source_events | Operational/Event | 클리핑, URL, 위키마킹 등 사용자 입력의 멱등 처리 | user_id + source_event_id Unique, Job 참조, received~ignored 상태 | 적용 | Schema only |
| user_source_documents | Master/Head | 사용자가 저장한 클리핑·URL 원본의 식별자, URL, 최신 버전과 상태 관리 | Personal Namespace 강제, URL·Hash Unique, Soft Delete | 적용 | Schema only |
| user_source_document_versions | Version/Raw | Frontmatter, Markdown 원문 또는 외부 Object URI를 버전별 보존 | source_document_id + version Unique, raw_content 또는 object_uri 필수 | 적용 | Schema only |
| wiki_versions | Snapshot/Version | 사용자 Wiki 전체 Build 버전과 문서·Chunk 수 보존 | user_id + version Unique, 사용자별 active 1개 | 적용 | Schema only |

웹 클리핑의 title, author, published, created, description, tags와 Markdown 본문은
user_source_document_versions에, source URL은 user_source_documents.canonical_url에
저장합니다. wiki_source_events는 요청 멱등성과 처리 상태를 담당하고, 원본 Version은
LLM Wiki 생성 뒤에도 사용자가 삭제하기 전까지 유지합니다. 자동 수집한 뉴스, RSS,
SNS 글은 Global Namespace의 wiki_documents 계열에 정규화해 저장하는 기존 설계입니다.

## 7. 사용자 관심사

| 테이블 | 성격 | 책임 | 핵심 관계·제약 | RLS | 현재 연결 |
|---|---|---|---|---|---|
| user_interest_profiles | Snapshot/Version | 특정 Wiki 버전에서 계산한 관심사 Profile | user_id + version Unique, 사용자별 active 1개, wiki_version_id FK | 적용 | Schema only |
| user_interests | Derived/Tree | Topic, Category, 점수와 계층 관계 보존 | profile_id + topic Unique, parent_interest_id Self FK, 점수 -1~1 | 적용 | Schema only |
| interest_evidence | Relation/History | 관심사 점수의 문서·사용자 이벤트 근거 | interest_id FK Cascade, document_id 또는 source_event_id 필수 | 적용 | Schema only |

## 8. Global Source와 Discovery

| 테이블 | 성격 | 책임 | 핵심 관계·제약 | RLS | 현재 연결 |
|---|---|---|---|---|---|
| global_sources | Master | RSS, News API, SNS 등 Connector 설정과 수집 정책 | source_key Unique, Secret 원문 대신 secret_ref, schedule/trust/quota | 없음 | Schema only |
| global_collection_runs | History/Operational | Source별 수집 Cursor, 처리 건수와 오류 이력 | source_id FK, 선택적 job_id FK, running~failed 상태 | 없음 | Schema only |
| global_trends | Derived | 시간 구간별 Global Topic과 신선도·중요도 점수 | 종료 시각이 시작 시각보다 커야 함, 점수 0~1 | 없음 | Schema only |
| global_trend_documents | Relation | Trend와 근거 Global 문서의 다대다 연결 | trend_id + document_id Composite PK, 양쪽 Cascade | 없음 | Schema only |
| discovery_candidates | Derived/Operational | 생성·추천 Pipeline에 넘길 Trend 또는 문서 후보 | trend_id 또는 document_id 필수, 점수 0~1, 만료 시각 | 없음 | Schema only |

뉴스·RSS·SNS 본문 자체는 별도 유형별 테이블이 아니라 Global Namespace의
wiki_documents와 wiki_document_versions에 저장합니다. global_sources는 Connector
설정, global_collection_runs는 수집 실행 이력을 소유합니다.

현재 wiki_documents에는 global_source_id나 collection_run_id FK가 없습니다.
수집 Source와 Run 추적은 source_type과 metadata/source_metadata에 의존하므로,
FK 수준의 출처 추적이 필요해지면 후속 Migration에서 명시적 관계를 추가해야 합니다.

discovery_candidates에는 user_id가 있지만 현재 RLS가 적용되지 않습니다. 사용자별
후보를 실제 운영에 사용하기 전 접근 범위와 RLS 적용 여부를 재검토해야 합니다.

## 9. 콘텐츠 생성

| 테이블 | 성격 | 책임 | 핵심 관계·제약 | RLS | 현재 연결 |
|---|---|---|---|---|---|
| generation_requests | Operational | Job과 사용자 Context를 고정한 생성 요청 | job_id Unique FK, user_context_snapshot_id FK, plan과 상태 관리 | 적용 | Schema only |
| generation_runs | History | Prompt/Model/Retrieval 설정이 고정된 생성 시도 | request_id + attempt_number Unique, Token/비용/지연 기록 | 적용 | Schema only |
| generated_content_candidates | Version | 발행 전 콘텐츠 본문과 버전, Hash 보존 | content_id + version Unique, Request/Run FK | 적용 | 참조 조회 |
| citations | Relation | 생성 콘텐츠의 주장과 문서·Chunk·URL 근거 연결 | candidate_id + ordinal Unique, document_version_id 또는 url 필수 | 적용 | Schema only |
| content_assets | Relation/Metadata | 이미지 등 Object Storage Asset Metadata 연결 | candidate_id FK Cascade, storage_uri 필수 | 적용 | Schema only |

generated_content_candidates의 body는 현재 text이며 별도의 content_format 제약은
없습니다. Markdown 사용 여부는 생성·발행 계약에서 명시해야 합니다.

## 10. 평가와 추천

| 테이블 | 성격 | 책임 | 핵심 관계·제약 | RLS | 현재 연결 |
|---|---|---|---|---|---|
| quality_evaluations | History/Derived | 콘텐츠 품질 점수, 통과 여부와 평가 근거 누적 | candidate_id FK Cascade, 선택적 score 0~1 | 적용 | Schema only |
| safety_evaluations | History/Derived | 안전성 통과 여부와 정책 Category 결과 누적 | candidate_id FK Cascade | 적용 | Schema only |
| recommendation_candidates | Derived/Operational | 사용자별 추천 후보 점수와 선택 상태 | user_id + content_id Unique, pending~expired 상태 | 적용 | Schema only |

## 11. Publish Snapshot과 발행

| 테이블 | 성격 | 책임 | 핵심 관계·제약 | RLS | 현재 연결 |
|---|---|---|---|---|---|
| publish_snapshots | Snapshot/Operational | Service Worker가 service-db에 반영할 불변 Payload와 전달 상태 | candidate_id FK, content_id + version Unique, Hash·Claim·Lease·Retry | 적용 | PostgreSQL 연결 |
| publish_attempts | History | 단건·Batch Claim별 발행 시도와 ACK 결과 | snapshot_id FK Cascade, snapshot + attempt/claim Unique | 적용 | PostgreSQL 연결 |

0002 Migration 이후 publish_snapshots의 상태는 ready, claimed, published, failed,
superseded입니다. claimed 상태에서는 claim_id, claimed_by, lease_expires_at이 모두
필수입니다. 재시도 가능한 실패는 next_attempt_at 이후 다시 Claim할 수 있습니다.

## 12. 이벤트, 보안과 운영

| 테이블 | 성격 | 책임 | 핵심 관계·제약 | RLS | 현재 연결 |
|---|---|---|---|---|---|
| event_outbox | Operational/Event | DB 변경과 Integration Event 발행을 같은 Transaction에 기록 | deduplication_key Unique, 재시도·Dead Letter 상태, Pending Index | 없음 | Schema only |
| event_inbox | History/Event | Consumer별 수신 Event 멱등성과 처리 결과 기록 | consumer_name + event_id Unique, payload_hash 검증 | 없음 | Schema only |
| api_keys | Master/Security | External API Key의 Hash, Prefix, Scope와 상태 관리 | Key 원문 미저장, key_prefix/key_hash Unique | 없음 | Schema only |
| usage_logs | History | Provider 호출의 Token, 비용, 지연과 Trace 누적 | 선택적 Job/Generation Run FK, 사용자 조회 Index | 적용 | Schema only |
| audit_logs | History | 관리자 변경과 민감 데이터 접근 이력 | Resource·Target User 조회 Index | 없음 | Schema only |

audit_logs는 설계상 Append-only지만 현재 Migration 자체에는 UPDATE/DELETE를
차단하는 Trigger나 전용 권한 설정이 없습니다. Production Role 권한으로
Append-only 성격을 강제해야 합니다.

## 13. Migration 관리

| 테이블 | 성격 | 책임 | 핵심 관계·제약 | RLS | 현재 연결 |
|---|---|---|---|---|---|
| schema_migrations | History/System | 적용된 Agent DB Migration 버전과 설명 기록 | version PK | 없음 | Migration Script |

빈 Volume과 기존 Volume 모두 Compose `post_start` Initializer가 미적용 Migration을
순서대로 적용한 뒤 Checksum이 변경된 개발 Seed를 한 번 적용합니다. Migration과
Seed가 최신 상태여야 Health Check를 통과합니다.

## 14. 핵심 관계 흐름

### Personal Wiki

    wiki_source_events
      → user_source_documents
      → user_source_document_versions
      → agent_jobs(personal_wiki_build)
      → wiki_documents
      → wiki_document_versions
      → wiki_document_sources
      → wiki_chunks
      → wiki_embeddings

### Global Source

    global_sources
      → global_collection_runs

    외부 문서
      → wiki_documents(namespace_key = global)
      → wiki_document_versions
      → wiki_chunks
      → wiki_embeddings
      → global_trend_documents / discovery_candidates

### 콘텐츠 생성과 발행

    user_context_snapshots + agent_jobs
      → generation_requests
      → generation_runs
      → generated_content_candidates
      → citations / content_assets / evaluations
      → publish_snapshots
      → publish_attempts

## 15. 관련 문서

- 컬럼별 상세 설명: agent-db-column-dictionary.md
- 논리 설계, 데이터 소유권과 배포 기준: agent-db-design.md
- 실제 초기 Schema: ../database/migrations/0001_initial.sql
- Publish Batch 확장: ../database/migrations/0002_publish_snapshot_batches.sql
- 웹 클리핑 Markdown 확장: ../database/migrations/0003_web_clipping_markdown.sql
- 사용자 원본과 LLM Wiki 분리: ../database/migrations/0004_separate_user_sources_from_llm_wiki.sql
- 로컬 실행과 Schema 검증: ../database/README.md
- Service Worker HTTP 계약: fastapi-mvp-api.md
