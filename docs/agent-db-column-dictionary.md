# Agent DB 컬럼 사전

> 기준: 2026-07-15. 43개 테이블, 497개 컬럼을 0001_initial.sql,
> 0002_publish_snapshot_batches.sql, 0003_web_clipping_markdown.sql,
> 0004_separate_user_sources_from_llm_wiki.sql,
> 0005_structure_llm_wiki_documents.sql 기준으로 정리했습니다.

이 문서는 Agent DB의 모든 테이블과 컬럼을 물리 Schema 수준에서 설명합니다.
테이블의 영역·성격·관계·RLS·런타임 연결 상태는
agent-db-table-catalog.md를 함께 참고합니다.

## 1. 읽는 법

- 타입은 현재 PostgreSQL에 적용된 실제 타입을 기준으로 표기합니다.
- 필수는 NULL을 허용하지 않고 애플리케이션 또는 DB가 값을 제공해야 한다는 뜻입니다.
- 선택은 NULL을 허용한다는 뜻입니다.
- 자동은 DB Default 또는 Generated Column으로 값이 만들어진다는 뜻입니다.
- UUID 기본값은 gen_random_uuid(), 시각 기본값은 clock_timestamp()입니다.
- FK, Unique, Check, Index의 전체 계약은 Migration과 테이블 카탈로그를 기준으로 합니다.
- JSONB 컬럼은 확장 지점이지만, 비밀정보나 검색·무결성에 중요한 값을 임의로
  JSONB에 넣지 않습니다.

## 2. 설정

### prompt_templates

Prompt의 안정적인 논리 식별자와 작업 유형을 관리합니다.

| 컬럼 | 타입 | 필수·기본값 | 설명 |
|---|---|---|---|
| id | uuid | 자동, PK | Prompt Template 내부 식별자 |
| prompt_key | text | 필수, Unique | 코드와 설정에서 참조하는 안정적인 Prompt Key |
| description | text | 선택 | Prompt의 목적과 사용 범위 설명 |
| task_type | text | 필수 | Prompt가 수행하는 작업 유형 |
| status | text | 자동, active | Template 상태: active, inactive, deleted |
| created_at | timestamptz | 자동 | Template 최초 생성 시각 |
| updated_at | timestamptz | 자동 | 마지막 변경 시각, Update Trigger가 갱신 |

### prompt_versions

Prompt 본문과 입출력 Schema의 불변 버전을 보존합니다.

| 컬럼 | 타입 | 필수·기본값 | 설명 |
|---|---|---|---|
| id | uuid | 자동, PK | Prompt Version 내부 식별자 |
| template_id | uuid | 필수, FK | 소속 prompt_templates 식별자 |
| version | integer | 필수 | Template 안에서 단조 증가하는 버전 번호 |
| status | text | 자동, draft | 버전 상태: draft, active, retired |
| system_prompt | text | 필수 | Model에 전달할 System Prompt 본문 |
| user_prompt_template | text | 선택 | 사용자 입력을 조합할 Prompt Template |
| input_schema | jsonb | 자동, 빈 Object | Prompt 입력 변수와 형식 계약 |
| output_schema | jsonb | 자동, 빈 Object | Model 출력 구조와 검증 계약 |
| checksum | text | 필수 | Prompt 내용 무결성 확인용 64자 Hash |
| change_reason | text | 선택 | 새 버전을 만든 이유 |
| created_by | text | 선택 | 버전을 생성한 관리자 또는 시스템 식별자 |
| activated_at | timestamptz | 선택 | active 상태로 전환된 시각 |
| created_at | timestamptz | 자동 | 버전 생성 시각 |

### model_configs

작업·플랜별 LLM Provider, Model, Parameter와 비용 기준을 버전 관리합니다.

| 컬럼 | 타입 | 필수·기본값 | 설명 |
|---|---|---|---|
| id | uuid | 자동, PK | Model Config 내부 식별자 |
| config_key | text | 필수 | 코드와 정책에서 참조하는 Config Key |
| version | integer | 필수 | Config Key 안에서 증가하는 버전 |
| task_type | text | 필수 | 이 설정을 적용할 생성·요약·평가 등의 작업 유형 |
| plan | text | 선택 | 적용 플랜: free, paid, 또는 NULL이면 공통 |
| provider | text | 필수 | OpenAI 등 Model Provider 식별자 |
| model_name | text | 필수 | Provider에 전달할 Model 이름 |
| parameters | jsonb | 자동, 빈 Object | Temperature, Token 제한 등 호출 Parameter |
| fallback_order | jsonb | 자동, 빈 Array | 장애·Quota 초과 시 사용할 대체 Model 순서 |
| input_cost_per_million | numeric(14,6) | 선택 | 입력 100만 Token당 추정 비용 |
| output_cost_per_million | numeric(14,6) | 선택 | 출력 100만 Token당 추정 비용 |
| status | text | 자동, draft | 설정 상태: draft, active, retired |
| created_by | text | 선택 | 설정을 생성한 관리자 또는 시스템 식별자 |
| change_reason | text | 선택 | 설정 변경 사유 |
| created_at | timestamptz | 자동 | 설정 버전 생성 시각 |

### retrieval_configs

Hybrid Search, Reranking, Chunk와 Citation 정책을 버전 관리합니다.

| 컬럼 | 타입 | 필수·기본값 | 설명 |
|---|---|---|---|
| id | uuid | 자동, PK | Retrieval Config 내부 식별자 |
| config_key | text | 필수 | 코드와 정책에서 참조하는 Config Key |
| version | integer | 필수 | Config Key 안에서 증가하는 버전 |
| plan | text | 선택 | 적용 플랜: free, paid, 또는 NULL이면 공통 |
| keyword_weight | numeric(5,4) | 자동, 0.35 | Hybrid Search에서 Keyword 점수 가중치 |
| vector_weight | numeric(5,4) | 자동, 0.65 | Hybrid Search에서 Vector 점수 가중치 |
| top_k | integer | 자동, 10 | 검색 단계에서 유지할 최대 후보 수 |
| similarity_threshold | numeric(5,4) | 선택 | Vector 결과를 수용할 최소 유사도 |
| reranking | jsonb | 자동, 빈 Object | Reranker Model과 점수 결합 정책 |
| chunk_policy | jsonb | 자동, 빈 Object | 검색 대상 Chunk 크기·중첩·필터 정책 |
| citation_policy | jsonb | 자동, 빈 Object | Citation 선택과 출력 정책 |
| status | text | 자동, draft | 설정 상태: draft, active, retired |
| created_at | timestamptz | 자동 | 설정 버전 생성 시각 |

### embedding_configs

Embedding Model, 차원, 거리 함수와 Chunk 정책 버전을 관리합니다.

| 컬럼 | 타입 | 필수·기본값 | 설명 |
|---|---|---|---|
| id | uuid | 자동, PK | Embedding Config 내부 식별자 |
| config_key | text | 필수 | 코드와 정책에서 참조하는 Config Key |
| version | integer | 필수 | Config Key 안에서 증가하는 버전 |
| provider | text | 필수 | Embedding Provider 식별자 |
| model_name | text | 필수 | Embedding Model 이름 |
| dimensions | integer | 자동, 1536 | Vector 차원, 현재 DDL에서는 1536으로 고정 |
| distance_metric | text | 자동, cosine | 검색 거리 함수: cosine, l2, inner_product |
| chunk_policy_version | text | 필수 | Embedding 생성에 사용한 Chunk 정책 버전 |
| status | text | 자동, draft | 설정 상태: draft, active, retired |
| created_at | timestamptz | 자동 | 설정 버전 생성 시각 |

## 3. 사용자 Context와 Agent Job

### user_context_snapshots

Service 원본을 복제하지 않고 AI 처리에 필요한 최소 사용자 설정만 버전별 저장합니다.

| 컬럼 | 타입 | 필수·기본값 | 설명 |
|---|---|---|---|
| id | uuid | 자동, PK | 사용자 Context Snapshot 내부 식별자 |
| user_id | text | 필수 | Service가 소유하는 사용자 식별자 |
| context_version | bigint | 필수 | 오래된 설정 덮어쓰기를 막는 단조 증가 버전 |
| plan | text | 필수 | 사용자 플랜: free 또는 paid |
| preferred_language | text | 자동, ko | 기본 생성·번역 언어 |
| personalization_enabled | boolean | 자동, true | 개인화 검색과 생성 적용 여부 |
| blocked_interest_ids | text[] | 자동, 빈 Array | 검색·생성에서 제외할 관심사 식별자 |
| blocked_source_ids | text[] | 자동, 빈 Array | 검색·생성에서 제외할 Source 식별자 |
| attributes | jsonb | 자동, 빈 Object | 명시적 Column 외의 최소 AI Context |
| checksum | text | 선택 | Context Payload 무결성 확인용 64자 Hash |
| created_at | timestamptz | 자동 | Snapshot 생성 시각 |
| deleted_at | timestamptz | 선택 | 사용자 삭제 등으로 Snapshot을 비활성화한 시각 |

### agent_jobs

API, Scheduler와 Worker가 공유할 비동기 작업의 상태와 재시도 경계를 저장합니다.

| 컬럼 | 타입 | 필수·기본값 | 설명 |
|---|---|---|---|
| id | uuid | 자동, PK | Agent Job 내부 식별자 |
| feature_id | text | 필수 | Job을 생성한 기능 명세 ID |
| job_type | text | 필수 | Worker가 선택할 작업 유형 |
| user_id | text | 선택 | 사용자별 작업이면 대상 사용자 식별자 |
| idempotency_key | text | 필수 | 같은 기능·사용자의 중복 Job 생성을 막는 Key |
| status | text | 자동, queued | queued, running, completed, failed, cancelled, dead_letter |
| priority | smallint | 자동, 100 | Dequeue 정렬 우선순위, 0~1000 |
| progress | smallint | 자동, 0 | 작업 진행률, 0~100 |
| payload | jsonb | 자동, 빈 Object | Worker에 전달할 입력 Payload |
| result | jsonb | 선택 | 완료된 Job의 기능별 결과 |
| result_version | integer | 자동, 1 | Result Payload Schema 버전 |
| error_code | text | 선택 | 마지막 실패의 안정적인 오류 코드 |
| error_message | text | 선택 | 비밀정보를 제외한 마지막 실패 설명 |
| retryable | boolean | 자동, false | 현재 실패가 재시도 가능한지 여부 |
| attempt_count | integer | 자동, 0 | 지금까지 시작한 실행 시도 횟수 |
| max_attempts | integer | 자동, 3 | 허용하는 최대 실행 시도 횟수 |
| queue_message_id | text | 선택 | Queue Adapter가 부여한 Message 식별자 |
| request_id | text | 선택 | 최초 API 요청 추적 식별자 |
| trace_id | text | 선택 | Service부터 Worker까지 연결할 Trace 식별자 |
| scheduled_at | timestamptz | 자동 | Job이 실행 가능해지는 시각 |
| locked_at | timestamptz | 선택 | Worker가 Job을 Claim한 시각 |
| locked_by | text | 선택 | Job을 Claim한 Worker 식별자 |
| started_at | timestamptz | 선택 | 실제 작업 실행 시작 시각 |
| completed_at | timestamptz | 선택 | 완료·실패 등 최종 처리 시각 |
| created_at | timestamptz | 자동 | Job 생성 시각 |
| updated_at | timestamptz | 자동 | 마지막 상태 변경 시각, Update Trigger가 갱신 |
| lease_expires_at | timestamptz | 선택 | Claim 소유권 만료 시각, 0002 Migration에서 추가 |

### agent_job_attempts

Job의 각 Worker 실행 시도를 독립적인 불변 이력으로 기록합니다.

| 컬럼 | 타입 | 필수·기본값 | 설명 |
|---|---|---|---|
| id | uuid | 자동, PK | Job Attempt 내부 식별자 |
| job_id | uuid | 필수, FK | 대상 agent_jobs 식별자 |
| user_id | text | 선택 | RLS와 사용자별 조회를 위한 경계 식별자 |
| attempt_number | integer | 필수 | Job 안에서 1부터 증가하는 시도 번호 |
| worker_id | text | 필수 | 실행을 담당한 Worker Instance 식별자 |
| status | text | 필수 | running, completed, failed, timed_out |
| error_code | text | 선택 | 해당 시도의 오류 코드 |
| error_message | text | 선택 | 해당 시도의 안전한 오류 설명 |
| details | jsonb | 자동, 빈 Object | 단계별 결과와 Provider Metadata |
| started_at | timestamptz | 자동 | 시도 시작 시각 |
| completed_at | timestamptz | 선택 | 시도 종료 시각 |

## 4. 지식 문서와 검색

### user_source_documents

사용자가 저장한 클리핑·URL 원본의 안정적인 식별자와 최신 Version을 관리합니다.

| 컬럼 | 타입 | 필수·기본값 | 설명 |
|---|---|---|---|
| id | uuid | 자동, PK | 사용자 원본 문서 내부 식별자 |
| user_id | text | 필수 | 원본을 소유한 사용자 식별자 |
| namespace_key | text | 필수 | 반드시 user/{user_id}인 격리 Namespace |
| source_type | text | 필수 | web_clipping, url, content_mark, content_save, memo, edit, conversation |
| canonical_url | text | 선택 | 클리핑·URL 원천 주소와 중복 판정 기준 |
| status | text | 자동, active | active, deleted, archived, superseded |
| current_version | integer | 자동, 1 | 현재 대표하는 user_source_document_versions 버전 번호 |
| content_hash | text | 필수 | Namespace 내 원본 중복 판정용 64자 Hash |
| metadata | jsonb | 자동, 빈 Object | 문서 Head 수준의 확장 Metadata |
| created_at | timestamptz | 자동 | 원본 문서 최초 생성 시각 |
| updated_at | timestamptz | 자동 | Head·상태가 마지막으로 변경된 시각 |
| deleted_at | timestamptz | 선택 | 원본이 Soft Delete된 시각 |

### user_source_document_versions

웹 클리핑 Frontmatter와 Markdown 본문 등 사용자가 제공한 원본을 버전별 보존합니다.

| 컬럼 | 타입 | 필수·기본값 | 설명 |
|---|---|---|---|
| id | uuid | 자동, PK | 사용자 원본 Version 내부 식별자 |
| source_document_id | uuid | 필수, FK | 소속 user_source_documents 식별자 |
| namespace_key | text | 필수 | 부모 원본 문서와 동일한 사용자 Namespace |
| source_event_id | uuid | 선택, FK | 이 Version을 수신한 wiki_source_events 식별자 |
| version | integer | 필수 | 원본 문서 안에서 1부터 증가하는 버전 번호 |
| title | text | 필수 | 클리퍼 Frontmatter의 title |
| author | text | 선택 | 클리퍼 Frontmatter의 author |
| published_at | timestamptz | 선택 | 외부 Source에 게시된 시각 |
| clipped_on | date | 선택 | 클리퍼 Frontmatter의 created 날짜 |
| description | text | 선택 | 클리퍼 Frontmatter의 description 원문 |
| tags | text[] | 자동, 빈 Array | 클리퍼 Frontmatter의 tags |
| raw_content | text | 선택 | 사용자가 저장한 Markdown·Text·HTML 원문 문자열 |
| content_format | text | 자동, markdown | markdown, plain_text, html, pdf, external_object |
| content_hash | text | 필수 | 이 원본 Version 내용의 64자 무결성 Hash |
| object_uri | text | 선택 | DB 밖에 보존한 대용량 HTML·PDF·원본 Payload URI |
| source_metadata | jsonb | 자동, 빈 Object | 클리퍼 형식, 파일명, Provider ID 등 수신 Metadata |
| created_at | timestamptz | 자동 | 원본 Version 생성 시각 |

raw_content와 object_uri 중 적어도 하나는 반드시 존재합니다. 웹 클리핑은 원문
Markdown을 raw_content에 저장하며, LLM Wiki 생성 뒤에도 자동 삭제하지 않습니다.

### wiki_documents

Agent가 생성한 Personal LLM Wiki와 정규화된 Global 문서의 식별자와 최신 버전을 관리합니다.

| 컬럼 | 타입 | 필수·기본값 | 설명 |
|---|---|---|---|
| id | uuid | 자동, PK | Wiki 문서 내부 식별자 |
| knowledge_scope | text | 필수 | 지식 범위: personal 또는 global |
| namespace_key | text | 필수 | 격리 Key: user/{user_id} 또는 global |
| user_id | text | 선택 | Personal 문서 소유 사용자, Global 문서는 NULL |
| source_event_id | uuid | 선택, FK | Personal Wiki 편입의 원천 wiki_source_events 식별자 |
| source_type | text | 필수 | clipping, rss, news_api 등 문서 유입 유형 |
| document_kind | text | 필수 | 문서 구조 유형: document, entity, concept, schema |
| document_key | text | 필수 | Namespace와 문서 유형 안에서 안정적으로 Upsert할 논리 Key |
| file_path | text | 필수 | Obsidian Vault 기준 Markdown 경로 |
| domain | text | 선택 | Entity 등의 업무·지식 Domain |
| canonical_url | text | 선택 | 중복 판정과 원문 연결에 사용할 정규 URL |
| language | text | 자동, und | 문서 언어 코드, 미확정은 und |
| status | text | 자동, active | active, deleted, archived, superseded |
| current_version | integer | 자동, 1 | 현재 대표하는 wiki_document_versions 버전 번호 |
| content_hash | text | 필수 | Namespace 내 내용 중복 판정용 64자 Hash |
| metadata | jsonb | 자동, 빈 Object | 생성 정책, 언어와 문서 공통 Metadata |
| created_at | timestamptz | 자동 | 문서 최초 생성 시각 |
| updated_at | timestamptz | 자동 | 마지막 Head·상태 변경 시각 |
| deleted_at | timestamptz | 선택 | 검색 대상에서 제거된 시각 |

### wiki_document_versions

Agent가 생성한 문서의 제목, 요약, 정규화 본문과 생성 정보를 버전별 보존합니다.

| 컬럼 | 타입 | 필수·기본값 | 설명 |
|---|---|---|---|
| id | uuid | 자동, PK | 문서 Version 내부 식별자 |
| document_id | uuid | 필수, FK | 소속 wiki_documents 식별자 |
| namespace_key | text | 필수 | 부모 문서와 동일해야 하는 격리 Namespace |
| version | integer | 필수 | 문서 안에서 1부터 증가하는 버전 번호 |
| title | text | 필수 | 정규화된 문서 제목 |
| summary | text | 선택 | 검색 Preview와 LLM Context용 요약 |
| normalized_content | text | 선택 | LLM이 구성한 Wiki 본문 또는 정규화된 Global 본문 |
| content_hash | text | 필수 | 이 Version 본문의 64자 무결성 Hash |
| object_uri | text | 선택 | DB 밖에 저장한 HTML, PDF, 원본 Payload의 URI |
| source_metadata | jsonb | 자동, 빈 Object | 생성 정책 또는 Global Provider 등 Version Metadata |
| created_by_job_id | uuid | 선택, FK | 이 Version을 생성한 agent_jobs 식별자 |
| created_at | timestamptz | 자동 | Version 생성 시각 |

normalized_content와 object_uri 중 적어도 하나는 반드시 존재합니다. 사용자 원본
Frontmatter와 Markdown은 이 테이블이 아니라 user_source_document_versions에 있습니다.

### wiki_document_sources

생성된 LLM Wiki Version이 참고한 사용자 원본 Version을 다대다로 연결합니다.

| 컬럼 | 타입 | 필수·기본값 | 설명 |
|---|---|---|---|
| wiki_document_version_id | uuid | 필수, FK, 복합 PK | 생성된 wiki_document_versions 식별자 |
| source_document_version_id | uuid | 필수, FK, 복합 PK | 참고한 user_source_document_versions 식별자 |
| namespace_key | text | 필수 | Wiki와 원본 양쪽에 동일하게 적용되는 사용자 Namespace |
| relation_type | text | 자동, source | source, citation, inspiration |
| relevance_score | numeric(8,6) | 선택 | Wiki와 원본의 관련도, 0~1 |
| created_at | timestamptz | 자동 | 출처 관계 생성 시각 |

### wiki_document_relations

Entity, Concept 등 생성된 Wiki 문서 사이의 현재 논리 Graph를 저장합니다.

| 컬럼 | 타입 | 필수·기본값 | 설명 |
|---|---|---|---|
| source_document_id | uuid | 필수, FK, 복합 PK | 관계를 설명하는 출발 wiki_documents 식별자 |
| target_document_id | uuid | 필수, FK, 복합 PK | 관계가 가리키는 대상 wiki_documents 식별자 |
| namespace_key | text | 필수 | 출발·대상 문서에 동일하게 적용되는 Namespace |
| relation_type | text | 필수, 복합 PK | entity_relation, applies_concept, related_concept, alias_of |
| metadata | jsonb | 자동, 빈 Object | Cardinality, 관계 이름, 병합 판단 등 확장 Metadata |
| created_at | timestamptz | 자동 | 관계 생성 시각 |

자기 자신을 대상으로 하는 관계는 금지되며, 복합 FK가 서로 다른
Namespace의 문서를 연결하지 못하게 막습니다.

### wiki_chunks

문서 Version을 검색과 LLM Context에 적합한 단위로 분할해 저장합니다.

| 컬럼 | 타입 | 필수·기본값 | 설명 |
|---|---|---|---|
| id | uuid | 자동, PK | Chunk 내부 식별자 |
| document_version_id | uuid | 필수, FK | Chunking한 LLM Wiki Version 식별자 |
| namespace_key | text | 필수 | 부모 Version과 동일한 검색 격리 Namespace |
| chunk_index | integer | 필수 | 문서 Version 안에서 0부터 증가하는 Chunk 순서 |
| content | text | 필수 | 검색과 Model 입력에 사용할 Chunk 본문 |
| token_count | integer | 선택 | 사용한 Tokenizer 기준 Chunk Token 수 |
| metadata | jsonb | 자동, 빈 Object | Heading 경로, 문자 Offset, Chunk 정책 등 Metadata |
| is_searchable | boolean | 자동, true | Keyword·Vector 검색 대상 포함 여부 |
| search_vector | tsvector | 자동 생성 | content에서 생성되는 PostgreSQL FTS Index 값 |
| created_at | timestamptz | 자동 | Chunk 생성 시각 |

### wiki_embeddings

Chunk의 의미 검색 Vector를 생성 설정과 함께 저장합니다.

| 컬럼 | 타입 | 필수·기본값 | 설명 |
|---|---|---|---|
| id | uuid | 자동, PK | Embedding 내부 식별자 |
| chunk_id | uuid | 필수, FK | 대상 wiki_chunks 식별자 |
| namespace_key | text | 필수 | 부모 Chunk와 동일한 검색 격리 Namespace |
| embedding_config_id | uuid | 필수, FK | 사용한 embedding_configs 식별자 |
| model_name | text | 필수 | 실제 호출한 Embedding Model 이름 |
| model_version | text | 필수 | 재현과 재색인을 위한 Model 버전 |
| embedding | vector(1536) | 필수 | 의미 유사도 검색에 사용하는 1536차원 Vector |
| content_hash | text | 필수 | Vector를 만든 Chunk 본문의 64자 Hash |
| created_at | timestamptz | 자동 | Embedding 생성 시각 |

## 5. Personal Wiki

### wiki_source_events

사용자가 선택한 Wiki 원천 이벤트와 멱등 처리 상태를 저장합니다.

| 컬럼 | 타입 | 필수·기본값 | 설명 |
|---|---|---|---|
| id | uuid | 자동, PK | Wiki Source Event 내부 식별자 |
| user_id | text | 필수 | 이벤트를 발생시킨 사용자 식별자 |
| source_event_id | text | 필수 | Service가 부여한 멱등 이벤트 식별자 |
| source_type | text | 필수 | web_clipping, url, content_mark, content_save, memo, edit, conversation, feedback, delete, rebuild |
| job_id | uuid | 선택, FK | 이벤트 처리를 담당하는 agent_jobs 식별자 |
| occurred_at | timestamptz | 선택 | Service에서 실제 사용자 행동이 발생한 시각 |
| source_url | text | 선택 | 클리핑·URL 원천 주소 |
| source_content_id | text | 선택 | 위키마킹 등 Service 콘텐츠 식별자 |
| object_uri | text | 선택 | 대용량 원문 또는 Attachment 저장 URI |
| payload | jsonb | 자동, 빈 Object | 이벤트 유형별 추가 입력 Payload |
| status | text | 자동, received | received, processing, completed, failed, ignored |
| retry_count | integer | 자동, 0 | 이벤트 처리 재시도 횟수 |
| error_code | text | 선택 | 마지막 처리 실패 코드 |
| error_message | text | 선택 | 비밀정보를 제외한 마지막 실패 설명 |
| processed_at | timestamptz | 선택 | 완료·실패·무시로 처리가 끝난 시각 |
| created_at | timestamptz | 자동 | Event 수신 시각 |
| updated_at | timestamptz | 자동 | 마지막 상태 변경 시각 |

### wiki_versions

사용자 Personal Wiki 전체 Build의 버전과 집계 결과를 저장합니다.

| 컬럼 | 타입 | 필수·기본값 | 설명 |
|---|---|---|---|
| id | uuid | 자동, PK | Wiki Build Version 내부 식별자 |
| user_id | text | 필수 | Wiki 소유 사용자 식별자 |
| namespace_key | text | 필수 | 반드시 user/{user_id}인 Wiki Build Namespace |
| version | bigint | 필수 | 사용자 안에서 증가하는 Wiki Build 버전 |
| status | text | 자동, building | building, active, failed, retired |
| document_count | integer | 자동, 0 | 이 Build에 포함된 활성 문서 수 |
| chunk_count | integer | 자동, 0 | 이 Build에 포함된 검색 가능 Chunk 수 |
| change_summary | jsonb | 자동, 빈 Object | 이전 버전 대비 추가·변경·삭제 요약 |
| built_by_job_id | uuid | 선택, FK | Wiki Build를 실행한 agent_jobs 식별자 |
| created_at | timestamptz | 자동 | Build 버전 생성 시각 |
| activated_at | timestamptz | 선택 | active 버전으로 전환된 시각 |

### wiki_version_documents

특정 Personal Wiki Build를 구성한 문서 Version과 당시 Vault 경로를 고정합니다.

| 컬럼 | 타입 | 필수·기본값 | 설명 |
|---|---|---|---|
| wiki_version_id | uuid | 필수, FK, 복합 PK | 소속 wiki_versions Build 식별자 |
| document_version_id | uuid | 필수, FK, 복합 PK | Build에 포함된 wiki_document_versions 식별자 |
| namespace_key | text | 필수 | Wiki Build와 문서 Version에 동일하게 적용되는 사용자 Namespace |
| file_path | text | 필수 | 해당 Build 시점의 Markdown 파일 경로 |
| created_at | timestamptz | 자동 | Build 구성에 문서 Version을 포함한 시각 |

하나의 Build에서 같은 파일 경로를 두 문서가 공유할 수 없고, 복합 FK로
Wiki Build와 문서 Version의 Namespace 일치를 보장합니다.

## 6. 사용자 관심사

### user_interest_profiles

특정 Wiki 버전에서 계산한 사용자 관심사 집합의 버전을 관리합니다.

| 컬럼 | 타입 | 필수·기본값 | 설명 |
|---|---|---|---|
| id | uuid | 자동, PK | 관심사 Profile 내부 식별자 |
| user_id | text | 필수 | Profile 소유 사용자 식별자 |
| version | bigint | 필수 | 사용자 안에서 증가하는 관심사 Profile 버전 |
| wiki_version_id | uuid | 선택, FK | 계산의 기준이 된 wiki_versions 식별자 |
| status | text | 자동, building | building, active, failed, retired |
| calculated_at | timestamptz | 자동 | 관심사 계산을 수행한 시각 |

### user_interests

Profile 안의 Topic, Category, 점수와 계층 관계를 저장합니다.

| 컬럼 | 타입 | 필수·기본값 | 설명 |
|---|---|---|---|
| id | uuid | 자동, PK | 관심사 Topic 내부 식별자 |
| profile_id | uuid | 필수, FK | 소속 user_interest_profiles 식별자 |
| user_id | text | 필수 | RLS와 사용자별 조회를 위한 사용자 식별자 |
| parent_interest_id | uuid | 선택, Self FK | 상위 관심사 Topic 식별자 |
| topic | text | 필수 | 추출·정규화한 관심사 주제 |
| category | text | 선택 | 서비스 분류 체계에 매핑된 Category |
| score | numeric(8,6) | 필수 | 선호·비선호 강도, -1~1 |
| confidence | numeric(8,6) | 필수 | 관심사 추론 신뢰도, 0~1 |
| is_blocked | boolean | 자동, false | 사용자 차단으로 검색·생성에서 제외할지 여부 |
| attributes | jsonb | 자동, 빈 Object | 계층·별칭·분류 Model 등 추가 Metadata |
| created_at | timestamptz | 자동 | 관심사 Row 생성 시각 |

### interest_evidence

관심사 점수의 근거가 된 문서 또는 사용자 Event를 연결합니다.

| 컬럼 | 타입 | 필수·기본값 | 설명 |
|---|---|---|---|
| id | uuid | 자동, PK | 관심사 근거 내부 식별자 |
| interest_id | uuid | 필수, FK | 대상 user_interests 식별자 |
| user_id | text | 필수 | RLS를 위한 사용자 식별자 |
| document_id | uuid | 선택, FK | 근거 Wiki 문서 식별자 |
| source_event_id | uuid | 선택, FK | 근거 사용자 Wiki Source Event 식별자 |
| weight | numeric(8,6) | 자동, 1 | 관심사 점수에 반영할 근거 가중치 |
| evidence | jsonb | 자동, 빈 Object | 근거 유형, 추출 문장, Model 판단 등 상세 |
| created_at | timestamptz | 자동 | 근거 연결 생성 시각 |

document_id와 source_event_id 중 적어도 하나는 반드시 존재합니다.

## 7. Global Source와 Discovery

### global_sources

외부 뉴스, RSS, SNS Connector의 수집 설정을 저장합니다. 인증정보 원문은 저장하지 않고 Secret Manager 참조만 보관합니다.

| 컬럼 | 타입 | 필수·기본값 | 설명 |
|---|---|---|---|
| id | uuid | 자동, PK | Global Source 내부 식별자 |
| source_key | text | 필수, Unique | Source를 안정적으로 식별하는 업무 Key |
| connector_type | text | 필수 | RSS, 뉴스 API, SNS 등 Connector 구현 유형 |
| display_name | text | 필수 | 운영 화면과 Log에 표시할 Source 이름 |
| status | text | 자동, active | active, paused, deleted |
| schedule_cron | text | 선택 | Source를 수집할 Cron 표현식 |
| keywords | text[] | 자동, 빈 Array | 수집 범위를 제한하는 Keyword 목록 |
| languages | text[] | 자동, 빈 Array | 수집 대상 언어 코드 목록 |
| categories | text[] | 자동, 빈 Array | 수집 대상 Category 목록 |
| secret_ref | text | 선택 | 인증정보 원문 대신 저장하는 Secret Manager Resource 참조 |
| quota_policy | jsonb | 자동, 빈 Object | 호출 한도, 재시도, Rate Limit 등 Quota 정책 |
| connector_config | jsonb | 자동, 빈 Object | Connector별 비민감 설정 |
| trust_score | numeric(5,4) | 선택 | Source 신뢰도, 0~1 |
| created_at | timestamptz | 자동 | Source 등록 시각 |
| updated_at | timestamptz | 자동 | Source 설정의 마지막 변경 시각 |

### global_collection_runs

Source별 수집 실행 상태, 처리 건수, 재시작 Cursor를 기록합니다.

| 컬럼 | 타입 | 필수·기본값 | 설명 |
|---|---|---|---|
| id | uuid | 자동, PK | 수집 실행 내부 식별자 |
| source_id | uuid | 필수, FK | 실행 대상 global_sources 식별자 |
| job_id | uuid | 선택, FK | 수집을 실행한 agent_jobs 식별자 |
| status | text | 자동, running | running, completed, partial, failed |
| cursor_before | jsonb | 선택 | 실행을 시작할 때의 외부 Source Cursor |
| cursor_after | jsonb | 선택 | 다음 실행이 이어받을 외부 Source Cursor |
| fetched_count | integer | 자동, 0 | 외부 Source에서 읽은 항목 수 |
| created_count | integer | 자동, 0 | 새 Wiki 문서로 생성한 항목 수 |
| duplicate_count | integer | 자동, 0 | 중복으로 판정해 생성하지 않은 항목 수 |
| failed_count | integer | 자동, 0 | 처리에 실패한 항목 수 |
| error_code | text | 선택 | 실행 실패를 분류하는 안정적인 오류 Code |
| error_message | text | 선택 | 운영 진단용 오류 상세 |
| started_at | timestamptz | 자동 | 수집 시작 시각 |
| completed_at | timestamptz | 선택 | 수집 종료 시각 |

### global_trends

여러 수집 문서에서 탐지한 Global Trend와 평가 점수를 저장합니다.

| 컬럼 | 타입 | 필수·기본값 | 설명 |
|---|---|---|---|
| id | uuid | 자동, PK | Trend 내부 식별자 |
| topic | text | 필수 | 탐지한 Trend 주제 |
| status | text | 자동, active | active, expired, rejected |
| freshness_score | numeric(8,6) | 선택 | 최신성 점수, 0~1 |
| importance_score | numeric(8,6) | 선택 | 중요도 점수, 0~1 |
| source_diversity_score | numeric(8,6) | 선택 | 서로 다른 Source에서 관측된 정도, 0~1 |
| window_started_at | timestamptz | 필수 | Trend 계산 대상 시간 구간 시작 |
| window_ended_at | timestamptz | 필수 | Trend 계산 대상 시간 구간 종료 |
| metadata | jsonb | 자동, 빈 Object | Keyword, Cluster, Model 결과 등 추가 정보 |
| created_at | timestamptz | 자동 | Trend 생성 시각 |

window_ended_at은 window_started_at보다 뒤여야 합니다.

### global_trend_documents

Global Trend와 근거 Wiki 문서를 N:M으로 연결합니다.

| 컬럼 | 타입 | 필수·기본값 | 설명 |
|---|---|---|---|
| trend_id | uuid | 필수, FK, 복합 PK | 대상 global_trends 식별자 |
| document_id | uuid | 필수, FK, 복합 PK | Trend의 근거가 된 wiki_documents 식별자 |
| relevance_score | numeric(8,6) | 필수 | 문서와 Trend의 관련도, 0~1 |

### discovery_candidates

Trend 또는 문서를 생성·추천 파이프라인에 넘기기 위한 후보 Queue입니다.

| 컬럼 | 타입 | 필수·기본값 | 설명 |
|---|---|---|---|
| id | uuid | 자동, PK | Discovery 후보 내부 식별자 |
| candidate_type | text | 필수 | generation 또는 recommendation |
| trend_id | uuid | 선택, FK | 후보의 근거가 된 global_trends 식별자 |
| document_id | uuid | 선택, FK | 후보의 근거가 된 wiki_documents 식별자 |
| user_id | text | 선택 | 특정 사용자에게 한정된 후보일 때의 사용자 식별자 |
| score | numeric(8,6) | 필수 | 후보 우선순위 점수, 0~1 |
| status | text | 자동, pending | pending, selected, rejected, expired |
| payload | jsonb | 자동, 빈 Object | 파이프라인에 넘길 후보별 추가 입력 |
| expires_at | timestamptz | 선택 | 후보 만료 시각 |
| created_at | timestamptz | 자동 | 후보 생성 시각 |

trend_id와 document_id 중 적어도 하나는 반드시 존재합니다.

## 8. 콘텐츠 생성

### generation_requests

콘텐츠 생성 요청을 Job, 사용자 Context Snapshot, 생성 조건에 연결합니다.

| 컬럼 | 타입 | 필수·기본값 | 설명 |
|---|---|---|---|
| id | uuid | 자동, PK | 생성 요청 내부 식별자 |
| job_id | uuid | 필수, Unique, FK | 생성 요청을 수행하는 agent_jobs 식별자 |
| user_id | text | 필수 | 요청 사용자 식별자 |
| user_context_snapshot_id | uuid | 필수, FK | 생성 입력으로 고정한 user_context_snapshots 식별자 |
| topic | text | 필수 | 생성할 콘텐츠의 주제 |
| content_type | text | 필수 | 생성 결과의 콘텐츠 유형 |
| plan | text | 필수 | free 또는 paid |
| language | text | 필수 | 생성 결과 언어 코드 |
| status | text | 자동, pending | pending, running, completed, failed, cancelled |
| parameters | jsonb | 자동, 빈 Object | 길이, Tone, Format 등 요청별 생성 Parameter |
| created_at | timestamptz | 자동 | 생성 요청 시각 |
| updated_at | timestamptz | 자동 | 요청 상태 또는 Parameter의 마지막 변경 시각 |

### generation_runs

한 생성 요청의 재시도별 Prompt·Model·검색 설정, 비용, 성능, 오류를 기록합니다.

| 컬럼 | 타입 | 필수·기본값 | 설명 |
|---|---|---|---|
| id | uuid | 자동, PK | 생성 실행 내부 식별자 |
| generation_request_id | uuid | 필수, FK | 대상 generation_requests 식별자 |
| user_id | text | 필수 | RLS와 사용자별 조회를 위한 사용자 식별자 |
| attempt_number | integer | 필수 | 요청 안에서 1부터 증가하는 실행 차수 |
| prompt_version_id | uuid | 선택, FK | 실행에 사용한 prompt_versions 식별자 |
| model_config_id | uuid | 선택, FK | 실행에 사용한 model_configs 식별자 |
| retrieval_config_id | uuid | 선택, FK | 실행에 사용한 retrieval_configs 식별자 |
| status | text | 자동, running | running, completed, failed, rejected |
| input_tokens | integer | 선택 | Provider에 전달한 입력 Token 수 |
| output_tokens | integer | 선택 | Provider가 생성한 출력 Token 수 |
| estimated_cost | numeric(14,6) | 선택 | 실행의 추정 비용 |
| latency_ms | integer | 선택 | 실행 지연 시간, Millisecond |
| error_code | text | 선택 | 실패를 분류하는 안정적인 오류 Code |
| error_message | text | 선택 | 운영 진단용 오류 상세 |
| run_metadata | jsonb | 자동, 빈 Object | Provider 응답 ID, Finish Reason 등 실행 Metadata |
| started_at | timestamptz | 자동 | 생성 실행 시작 시각 |
| completed_at | timestamptz | 선택 | 생성 실행 종료 시각 |

### generated_content_candidates

Service DB에 발행하기 전 생성 결과의 본문과 Version을 보존합니다. Markdown 본문은 body에 문자열로 저장합니다.

| 컬럼 | 타입 | 필수·기본값 | 설명 |
|---|---|---|---|
| id | uuid | 자동, PK | 생성 콘텐츠 후보 내부 식별자 |
| generation_request_id | uuid | 필수, FK | 원본 generation_requests 식별자 |
| generation_run_id | uuid | 필수, FK | 실제 결과를 만든 generation_runs 식별자 |
| user_id | text | 필수 | 콘텐츠 소유 사용자 식별자 |
| content_id | text | 필수 | Service DB와 공유하는 콘텐츠 업무 식별자 |
| version | integer | 필수 | content_id 안에서 1부터 증가하는 Version |
| content_type | text | 필수 | 콘텐츠 유형 |
| status | text | 자동, draft | draft, ready, published, failed, archived, superseded, rejected |
| title | text | 필수 | 생성 콘텐츠 제목 |
| summary | text | 필수 | 생성 콘텐츠 요약 |
| body | text | 필수 | Markdown 등 완성된 콘텐츠 본문 문자열 |
| structured_body | jsonb | 자동, 빈 Object | Section, Block 등 구조화된 본문 표현 |
| snapshot_hash | text | 필수 | 본문 Snapshot의 무결성과 중복을 확인하는 Hash |
| created_at | timestamptz | 자동 | 후보 생성 시각 |
| updated_at | timestamptz | 자동 | 후보 상태 또는 본문의 마지막 변경 시각 |

content_id와 version의 조합은 유일합니다.

### citations

생성 콘텐츠의 주장과 근거 문서·Chunk·외부 URL을 출력 순서대로 연결합니다.

| 컬럼 | 타입 | 필수·기본값 | 설명 |
|---|---|---|---|
| id | uuid | 자동, PK | 인용 내부 식별자 |
| candidate_id | uuid | 필수, FK | 대상 generated_content_candidates 식별자 |
| user_id | text | 필수 | RLS를 위한 사용자 식별자 |
| ordinal | integer | 필수 | 후보 안에서 0부터 시작하는 인용 순서 |
| document_version_id | uuid | 선택, FK | 인용한 wiki_document_versions 식별자 |
| chunk_id | uuid | 선택, FK | 인용한 wiki_chunks 식별자 |
| title | text | 필수 | 화면에 표시할 출처 제목 |
| url | text | 선택 | 외부 출처 URL |
| quoted_text | text | 선택 | 주장을 뒷받침하는 짧은 인용문 |
| claim_paths | text[] | 자동, 빈 Array | 인용이 뒷받침하는 구조화 본문의 경로 목록 |
| citation_hash | text | 선택 | 인용 내용 무결성을 확인하는 64자 Hash |
| created_at | timestamptz | 자동 | 인용 생성 시각 |

document_version_id와 url 중 적어도 하나는 반드시 존재합니다.

### content_assets

이미지 등 Object Storage Asset의 파일 자체가 아닌 위치와 Metadata를 저장합니다.

| 컬럼 | 타입 | 필수·기본값 | 설명 |
|---|---|---|---|
| id | uuid | 자동, PK | Asset 내부 식별자 |
| candidate_id | uuid | 필수, FK | Asset을 사용하는 generated_content_candidates 식별자 |
| user_id | text | 필수 | Asset 소유 사용자 식별자 |
| asset_type | text | 필수 | image, thumbnail 등 Asset 유형 |
| status | text | 자동, pending | pending, ready, failed, deleted |
| storage_uri | text | 필수 | Object Storage의 GCS URI 등 파일 위치 |
| content_type | text | 선택 | image/png 등 Media Type |
| byte_size | bigint | 선택 | 파일 크기, Byte |
| checksum | text | 선택 | 파일 무결성을 확인하는 64자 Checksum |
| metadata | jsonb | 자동, 빈 Object | 폭, 높이, 생성 Model 등 Asset Metadata |
| created_at | timestamptz | 자동 | Asset 등록 시각 |

## 9. 평가와 추천

### quality_evaluations

생성 콘텐츠의 품질 평가 결과를 평가기별로 누적합니다.

| 컬럼 | 타입 | 필수·기본값 | 설명 |
|---|---|---|---|
| id | uuid | 자동, PK | 품질 평가 내부 식별자 |
| candidate_id | uuid | 필수, FK | 평가 대상 generated_content_candidates 식별자 |
| user_id | text | 필수 | RLS를 위한 사용자 식별자 |
| evaluator | text | 필수 | Rule, Model, 평가 Version을 식별하는 이름 |
| score | numeric(8,6) | 선택 | 종합 품질 점수, 0~1 |
| passed | boolean | 필수 | 품질 Gate 통과 여부 |
| metrics | jsonb | 자동, 빈 Object | 정확성, 가독성 등 세부 품질 지표 |
| reasons | jsonb | 자동, 빈 Array | 통과·실패 사유 목록 |
| created_at | timestamptz | 자동 | 평가 수행 시각 |

### safety_evaluations

생성 콘텐츠의 안전성 평가와 위험 Category를 평가기별로 누적합니다.

| 컬럼 | 타입 | 필수·기본값 | 설명 |
|---|---|---|---|
| id | uuid | 자동, PK | 안전성 평가 내부 식별자 |
| candidate_id | uuid | 필수, FK | 평가 대상 generated_content_candidates 식별자 |
| user_id | text | 필수 | RLS를 위한 사용자 식별자 |
| evaluator | text | 필수 | Rule, Model, 평가 Version을 식별하는 이름 |
| passed | boolean | 필수 | 안전성 Gate 통과 여부 |
| categories | jsonb | 자동, 빈 Object | Category별 탐지 결과와 점수 |
| reasons | jsonb | 자동, 빈 Array | 통과·실패 사유 목록 |
| created_at | timestamptz | 자동 | 평가 수행 시각 |

### recommendation_candidates

사용자에게 노출할 후속 콘텐츠 후보와 추천 점수를 저장합니다.

| 컬럼 | 타입 | 필수·기본값 | 설명 |
|---|---|---|---|
| id | uuid | 자동, PK | 추천 후보 내부 식별자 |
| user_id | text | 필수 | 추천 대상 사용자 식별자 |
| content_id | text | 필수 | 추천할 Service 콘텐츠 식별자 |
| score | numeric(8,6) | 필수 | 추천 순위 계산에 사용하는 점수 |
| reason | jsonb | 자동, 빈 Object | 관심사, Trend 등 추천 근거 |
| status | text | 자동, pending | pending, selected, rejected, expired |
| created_at | timestamptz | 자동 | 추천 후보 생성 시각 |
| expires_at | timestamptz | 선택 | 추천 후보 만료 시각 |

user_id와 content_id의 조합은 유일합니다.

## 10. 발행

### publish_snapshots

Service Worker가 가져갈 발행 Payload를 Version과 Hash가 고정된 Snapshot으로 저장하고, Batch Claim과 Lease 상태를 관리합니다.

| 컬럼 | 타입 | 필수·기본값 | 설명 |
|---|---|---|---|
| id | uuid | 자동, PK | 발행 Snapshot 내부 식별자 |
| candidate_id | uuid | 필수, FK | 원본 generated_content_candidates 식별자 |
| user_id | text | 필수 | 콘텐츠 소유 사용자 식별자 |
| content_id | text | 필수 | Service DB와 공유하는 콘텐츠 업무 식별자 |
| version | integer | 필수 | content_id 안에서 1부터 증가하는 Version |
| snapshot_hash | text | 필수 | 발행 Payload 무결성과 중복을 확인하는 Hash |
| payload | jsonb | 필수 | Service Worker가 그대로 소비할 불변 발행 Payload |
| status | text | 자동, ready | ready, claimed, published, failed, superseded |
| created_at | timestamptz | 자동 | Snapshot 생성 시각 |
| acknowledged_at | timestamptz | 선택 | Service Worker가 발행 결과를 확인한 시각 |
| failure_reason | text | 선택 | 최종 또는 최근 발행 실패 사유 |
| claim_id | uuid | 선택 | 한 번의 Batch Claim을 식별하는 값 |
| claimed_by | text | 선택 | Snapshot을 점유한 Worker 식별자 |
| lease_expires_at | timestamptz | 선택 | 점유가 만료되어 재처리 가능해지는 시각 |
| attempt_count | integer | 자동, 0 | Snapshot 발행을 시도한 누적 횟수 |
| next_attempt_at | timestamptz | 선택 | 실패 후 다음 재시도가 가능한 시각 |

status가 claimed이면 claim_id, claimed_by, lease_expires_at이 모두 존재해야 합니다. content_id와 version의 조합은 유일합니다.

### publish_attempts

Snapshot 발행 요청과 Worker 처리 결과를 시도 단위로 기록합니다.

| 컬럼 | 타입 | 필수·기본값 | 설명 |
|---|---|---|---|
| id | uuid | 자동, PK | 발행 시도 내부 식별자 |
| snapshot_id | uuid | 필수, FK | 대상 publish_snapshots 식별자 |
| user_id | text | 필수 | 콘텐츠 소유 사용자 식별자 |
| attempt_number | integer | 필수 | Snapshot 안에서 1부터 증가하는 시도 차수 |
| worker_event_id | text | 선택 | Service Worker가 반환한 Event 식별자 |
| status | text | 필수 | requested, published, failed |
| failure_reason | text | 선택 | 발행 실패 사유 |
| requested_at | timestamptz | 자동 | 발행을 요청한 시각 |
| acknowledged_at | timestamptz | 선택 | Worker 결과를 확인한 시각 |
| claim_id | uuid | 선택 | 시도가 속한 Batch Claim 식별자 |
| claimed_by | text | 선택 | 요청 당시 Snapshot을 점유한 Worker 식별자 |
| lease_expires_at | timestamptz | 선택 | 요청 당시 Claim Lease 만료 시각 |
| retryable | boolean | 선택 | 실패가 재시도 가능한 유형인지 여부 |

snapshot_id와 attempt_number의 조합, snapshot_id와 claim_id의 조합은 각각 유일합니다.

## 11. Event와 보안·운영

### event_outbox

Agent DB의 상태 변경과 Integration Event 발행을 같은 Transaction으로 묶는 Outbox입니다.

| 컬럼 | 타입 | 필수·기본값 | 설명 |
|---|---|---|---|
| id | uuid | 자동, PK | Outbox Event 내부 식별자 |
| aggregate_type | text | 필수 | Event가 속한 Aggregate 유형 |
| aggregate_id | text | 필수 | Event가 속한 Aggregate 식별자 |
| event_type | text | 필수 | Integration Event 유형 |
| schema_version | integer | 자동, 1 | Event Payload Schema Version |
| deduplication_key | text | 필수, Unique | 중복 발행을 막는 업무 Key |
| payload | jsonb | 필수 | 발행할 Event Payload |
| status | text | 자동, pending | pending, publishing, published, failed, dead_letter |
| attempt_count | integer | 자동, 0 | Event 발행 시도 횟수 |
| available_at | timestamptz | 자동 | Event를 발행 대상으로 선택할 수 있는 시각 |
| published_at | timestamptz | 선택 | Event 발행 완료 시각 |
| last_error | text | 선택 | 최근 발행 실패 사유 |
| created_at | timestamptz | 자동 | Outbox Event 생성 시각 |

### event_inbox

외부 Event를 Consumer별로 멱등 처리하기 위한 수신 기록입니다.

| 컬럼 | 타입 | 필수·기본값 | 설명 |
|---|---|---|---|
| id | uuid | 자동, PK | Inbox Event 내부 식별자 |
| consumer_name | text | 필수 | Event를 처리하는 Consumer 이름 |
| event_id | text | 필수 | 외부 Event 식별자 |
| event_type | text | 필수 | 외부 Event 유형 |
| schema_version | integer | 필수 | 수신한 Event Payload Schema Version |
| payload_hash | text | 필수 | Payload 무결성과 충돌을 확인하는 64자 Hash |
| status | text | 자동, received | received, processed, failed, ignored |
| received_at | timestamptz | 자동 | Event 수신 시각 |
| processed_at | timestamptz | 선택 | Event 처리 완료 시각 |
| error_message | text | 선택 | Event 처리 실패 상세 |

consumer_name과 event_id의 조합은 유일합니다.

### api_keys

외부 API 인증 Key의 원문 대신 식별 Prefix와 Hash, 권한, 수명주기를 저장합니다.

| 컬럼 | 타입 | 필수·기본값 | 설명 |
|---|---|---|---|
| id | uuid | 자동, PK | API Key 내부 식별자 |
| key_prefix | text | 필수, Unique | 운영자가 Key를 구분할 수 있는 비밀이 아닌 Prefix |
| key_hash | text | 필수, Unique | 검증에 사용하는 API Key Hash |
| principal_id | text | 필수 | Key를 소유하거나 사용하는 Principal 식별자 |
| scopes | text[] | 자동, 빈 Array | 허용된 API 권한 Scope 목록 |
| status | text | 자동, active | active, revoked, expired |
| expires_at | timestamptz | 선택 | Key 만료 시각 |
| last_used_at | timestamptz | 선택 | Key가 마지막으로 사용된 시각 |
| created_at | timestamptz | 자동 | Key 발급 시각 |
| revoked_at | timestamptz | 선택 | Key 폐기 시각 |

### usage_logs

Provider 호출의 Token, 비용, 지연, 추적 정보를 사용량 단위로 기록합니다.

| 컬럼 | 타입 | 필수·기본값 | 설명 |
|---|---|---|---|
| id | uuid | 자동, PK | 사용량 Log 내부 식별자 |
| job_id | uuid | 선택, FK | 호출이 속한 agent_jobs 식별자 |
| generation_run_id | uuid | 선택, FK | 호출이 속한 generation_runs 식별자 |
| user_id | text | 선택 | 비용 또는 사용량을 귀속할 사용자 식별자 |
| feature_id | text | 필수 | 비용을 발생시킨 기능 식별자 |
| provider | text | 필수 | OpenAI 등 외부 Provider 이름 |
| model_name | text | 선택 | 호출한 Model 이름 |
| operation | text | 필수 | generation, embedding 등 호출 작업 유형 |
| input_tokens | integer | 자동, 0 | 입력 Token 수 |
| output_tokens | integer | 자동, 0 | 출력 Token 수 |
| request_count | integer | 자동, 1 | 집계 Row가 나타내는 요청 횟수 |
| estimated_cost | numeric(14,6) | 자동, 0 | 호출의 추정 비용 |
| latency_ms | integer | 선택 | 호출 지연 시간, Millisecond |
| status | text | 필수 | succeeded, failed, cached |
| request_id | text | 선택 | API 요청을 추적하는 식별자 |
| trace_id | text | 선택 | 분산 Trace 식별자 |
| metadata | jsonb | 자동, 빈 Object | Provider 응답 ID 등 추가 운영 정보 |
| created_at | timestamptz | 자동 | 사용량 발생 시각 |

### audit_logs

관리자 변경과 민감 데이터 접근을 변경하지 않는 Append-only Audit로 기록합니다.

| 컬럼 | 타입 | 필수·기본값 | 설명 |
|---|---|---|---|
| id | uuid | 자동, PK | Audit Log 내부 식별자 |
| actor_type | text | 필수 | user, service, admin 등 행위자 유형 |
| actor_id | text | 필수 | 행위자 식별자 |
| action | text | 필수 | 수행한 작업 이름 |
| resource_type | text | 필수 | 대상 Resource 유형 |
| resource_id | text | 선택 | 대상 Resource 식별자 |
| target_user_id | text | 선택 | 작업 또는 조회의 대상 사용자 식별자 |
| request_id | text | 선택 | API 요청 추적 식별자 |
| trace_id | text | 선택 | 분산 Trace 식별자 |
| source_ip | inet | 선택 | 요청을 보낸 IP 주소 |
| succeeded | boolean | 필수 | 작업 성공 여부 |
| details | jsonb | 자동, 빈 Object | 변경 전후 값, 실패 사유 등 Audit 상세 |
| created_at | timestamptz | 자동 | Audit Event 발생 시각 |

### schema_migrations

Agent DB에 적용된 Migration Version을 기록합니다.

| 컬럼 | 타입 | 필수·기본값 | 설명 |
|---|---|---|---|
| version | integer | 필수, PK | 순서대로 증가하는 Migration Version |
| description | text | 필수 | Migration의 사람이 읽을 수 있는 설명 |
| applied_at | timestamptz | 자동 | Migration 적용 시각 |

## 12. 관련 문서

- [Agent DB 테이블 카탈로그](agent-db-table-catalog.md): 영역별 Table 성격과 관계
- [Agent DB 상세 설계](agent-db-design.md): 설계 원칙, ERD, RLS와 운영 정책
- [초기 Migration](../database/migrations/0001_initial.sql): 기본 Schema 정의
- [발행 Batch Migration](../database/migrations/0002_publish_snapshot_batches.sql): Claim과 Lease 확장
- [웹 클리핑 Markdown Migration](../database/migrations/0003_web_clipping_markdown.sql): Frontmatter와 본문 형식 확장
- [사용자 원본·LLM Wiki 분리 Migration](../database/migrations/0004_separate_user_sources_from_llm_wiki.sql): 원본 테이블과 출처 관계 추가
- [LLM Wiki Vault 구조 Migration](../database/migrations/0005_structure_llm_wiki_documents.sql): 문서 유형·관계·Build 구성 추가
- [Database 실행 안내](../database/README.md): Local DB 기동과 Migration 적용 방법
