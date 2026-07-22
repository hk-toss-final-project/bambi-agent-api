# Bambi Agent API 프로젝트 구조

이 문서는 `agent-api-feature-spec.md`의 실제 기능 영역 1~43절을 코드 구조에 매핑한 결과입니다. MVP의 웹 클리핑 Payload, PostgreSQL 저장과 Worker 데이터 플로우는 `fastapi-mvp-api.md`를 구현 계약으로 사용하고, 그 밖의 상세 계약은 확정 전까지 공통 경계만 유지합니다.

## 스캐폴드 원칙

- 전체 기능 625개는 기능 ID를 소문자로 바꾼 비동기 함수와 1:1로 연결됩니다. 예: `BAMBI-009` → `bambi_009(...)`.
- 미구현 스캐폴드 함수는 공통 `FeatureRequest → FeatureResult` 계약과 명시적인 `NotImplementedError`를 유지합니다. 구현된 함수는 기능에 맞는 typed 시그니처·반환값과 `Protocol` 기반 의존성을 사용합니다.
- MVP 체크리스트 완료 58개와 별도 구현된 `SCH-009`는 실행 가능하며, 나머지 566개는 명시적인 미구현 스텁입니다.
- 각 기능 영역의 `api.py`는 구현을 포함하지 않는 공개 facade이며, `features/` 아래 응집도 기준으로 분리된 구현 모듈의 함수를 import하고 `__all__`로 노출합니다.
- 전용 MVP 범위 문서가 구현 우선순위의 기준입니다. 해당 71개 함수 바로 위에 `# MVP:` 주석을 붙였습니다.
- 전체 명세 44~46절의 MVP·2차·3차 항목은 기존 기능을 묶은 로드맵이므로 실행 함수를 중복 생성하지 않았습니다.
- API Request/Response 상세 필드가 확정되면 `app/schemas/`에 도메인별 Pydantic 모델을 추가하고, `app/routers/`의 라우터에서 기능 함수를 호출합니다.
- Agent DB의 물리 스키마와 운영 기준은 `docs/agent-db-design.md`, 실행 가능한 SQL은 `database/`에서 관리합니다.

## 최상위 구조

```text
bambi-agent-api/
├── app/                    # FastAPI 앱, 설정, 미들웨어, 라우터, 스키마
├── agent/                  # LangGraph 상태, 그래프, 노드, Tool, Prompt, Agent 기능
├── domain/                 # 사용자 컨텍스트, 개인 Wiki, 콘텐츠, Job, 발행 도메인
├── infrastructure/         # Provider, DB, Vector, Queue, Event, Source, Object Storage
├── database/               # PostgreSQL Migration과 실제 DB 계약 검사
├── workers/                # 작업 유형별 비동기 Worker 진입점
├── scheduler/              # 정기 작업 등록과 실행 진입점
├── mcp_server/             # MVP 이후 MCP Server와 Tool 경계
├── shared/                 # 공통 함수 계약과 비기능 정책
├── tests/                  # 명세-스캐폴드 정합성과 앱 조립 테스트
├── bench/                  # 실제 LLM 기능 구현 후 추가할 품질 벤치마크
├── docs/                   # 전체 기능 명세, MVP 범위, 구조·DB 설계 문서
└── compose.yaml            # 로컬 PostgreSQL 17 + pgvector 실행 구성
```

## 기능 구현 패턴

```text
domain/personal_wiki/documents/
├── api.py                       # 외부 계층이 사용하는 공개 facade
└── features/                    # 실제 기능 구현 전용 패키지
    ├── commands.py              # PWIKI-002, PWIKI-004, PWIKI-005
    ├── queries.py               # PWIKI-003
    ├── deduplication.py         # PWIKI-008
    └── normalization.py         # PWIKI-011
```

- Router, Worker, Agent 등 외부 호출자는 `api.py`에서 기능을 import합니다.
- 구현 함수는 `features/` 아래에서 역할과 변경 이유가 같은 기능끼리 모듈에 묶으며, 복잡한 기능만 단독 파일로 분리합니다.
- `features/` 구현 모듈은 `api.py`를 역으로 import하지 않아 순환 의존성을 방지합니다.
- MVP 주석과 기능 docstring은 facade가 아니라 실제 구현 함수에 유지합니다.
- 기존 서비스 객체·저장소·Provider처럼 실행 시점에 결합되는 의존성은 typed 인자나 `Protocol`로 기능 함수에 전달합니다. 구현된 기능은 호출자 제공 콜백이 아니라 `features/` 함수가 검증·변환·오케스트레이션을 소유합니다.
- 범용 `FeatureRequest/FeatureResult` 실행 위임은 이번 전환 제외 범위인 `agent/bambi/**`의 호환 경계에만 남기고, 다른 운영 경로에서는 사용하지 않습니다.
- 외부 모듈의 `features/` 직접 import와 `api.py` 내부 함수 구현은 정합성 테스트로 차단합니다.
- 적용된 기능별 경계와 런타임 호출 상태는 [`feature-facade-migration.md`](feature-facade-migration.md)에 기록합니다.

## 기능 영역별 파일 매핑

| 절 | 기능 영역 | ID Prefix | 공개 facade |
|---:|---|---|---|
| 1 | FastAPI 진입점 | `SYS` | `app/core/api.py` |
| 2 | 내부 API 인증 | `AUTH` | `app/security/internal_auth/api.py` |
| 3 | 사용자 컨텍스트 관리 | `CTX` | `domain/user_context/api.py` |
| 4 | 사용자 Wiki Source Event | `WSE` | `domain/personal_wiki/source_events/api.py` |
| 5 | User Personal LLM Wiki | `PWIKI` | `domain/personal_wiki/documents/api.py` |
| 6 | 개인 Wiki Chunk 및 Embedding | `PWE` | `domain/personal_wiki/embeddings/api.py` |
| 7 | 개인 Wiki 검색 및 RAG | `PRAG` | `domain/personal_wiki/retrieval/api.py` |
| 8 | 사용자 관심사 분류 | `INT` | `domain/interests/api.py` |
| 9 | Personal Wiki Builder Agent | `WBA` | `agent/wiki_builder/api.py` |
| 10 | Global Source 관리 | `GS` | `infrastructure/sources/management/api.py` |
| 11 | Global Source Collector | `COL` | `infrastructure/sources/connectors/api.py` |
| 12 | Global Source 정제 및 저장 | `GSP` | `infrastructure/sources/processing/api.py` |
| 13 | Global Discovery 및 Trend | `DISC` | `agent/discovery/api.py` |
| 14 | LLM 공통 기능 | `LLM` | `agent/llm/api.py` |
| 15 | Prompt 관리 | `PROMPT` | `agent/prompts/api.py` |
| 16 | Model Config 관리 | `MODEL` | `agent/llm/model_config/api.py` |
| 17 | Retrieval 설정 관리 | `RET` | `agent/retrieval/api.py` |
| 18 | 콘텐츠 생성 에이전트 밤비 | `BAMBI` | `agent/bambi/api.py` |
| 19 | 생성 콘텐츠 유형 | `CTYPE` | `domain/content/types/api.py` |
| 20 | 플랜별 콘텐츠 차등화 | `PLAN` | `domain/content/plans/api.py` |
| 21 | 콘텐츠 품질 관리 | `QUALITY` | `agent/evaluation/quality/api.py` |
| 22 | 요약 기능 | `SUM` | `agent/summarization/api.py` |
| 23 | 번역 기능 | `TR` | `agent/translation/api.py` |
| 24 | 이미지 자료 생성 | `IMG` | `agent/images/api.py` |
| 25 | 추천 기능 | `REC` | `agent/recommendation/api.py` |
| 26 | Agent Job 관리 | `JOB` | `domain/jobs/api.py` |
| 27 | Agent Worker | `WORKER` | `workers/api.py` |
| 28 | Worker 공통 기능 | `WC` | `workers/runtime/api.py` |
| 29 | Scheduler | `SCH` | `scheduler/api.py` |
| 30 | Queue 및 Integration Event | `QUEUE/EVT` | `infrastructure/messaging/api.py` |
| 31 | Service API 연동 | `SVC` | `app/routers/service/api.py` |
| 32 | Service Worker 연동 | `SW` | `app/routers/service_worker/api.py` |
| 33 | 발행 콘텐츠 관리 | `PUB` | `domain/publishing/api.py` |
| 34 | 관리자 기능 | `ADMIN` | `app/routers/admin/api.py` |
| 35 | 자체 API Key | `KEY` | `app/security/api_keys/api.py` |
| 36 | External Agent API | `EXT` | `app/routers/external/api.py` |
| 37 | MCP Server | `MCP` | `mcp_server/server/api.py` |
| 38 | MCP Tool | `MCPTOOL` | `mcp_server/tools/api.py` |
| 39 | Agent DB | `DB` | `infrastructure/persistence/api.py` |
| 40 | Object Storage | `OBJ` | `infrastructure/storage/api.py` |
| 41 | 로그 및 모니터링 | `OBS` | `infrastructure/observability/api.py` |
| 42 | 보안 및 개인정보 | `SEC` | `app/security/privacy/api.py` |
| 43 | 비기능 요구사항 | `NFR` | `shared/resilience/api.py` |

## MVP 구현 흐름

1. Browser Extension의 클리핑은 service-api 인증을 거쳐 Agent API에 전달되고, Source Event·사용자 원본 Markdown Version·Job을 한 DB Transaction으로 저장합니다.
2. `workers/features/personal_wiki_builder.py`가 저장된 source_document_version_id를 기준으로 LLM Wiki 문서·출처 관계·Chunk를 구성합니다. Embedding 생성·저장은 Vector 검색 도입 전까지 실행 경로에서 제외합니다.
3. `workers/features/global_source_collector.py`가 Naver, GDELT, NewsAPI Connector를 실행하고 정규화·중복 제거합니다.
4. Worker Runtime이 실행 가능한 Job을 `FOR UPDATE SKIP LOCKED`로 Batch Claim하고 작업별 동시성을 제한합니다.
5. `workers/features/bambi_generation.py`가 개인 Wiki와 Global Source 검색 결과로 각 콘텐츠를 독립 생성합니다.
6. 생성 후보와 Citation, Ready Publish Snapshot을 저장하고 Content Ready 이벤트를 발행합니다.
7. Service Worker가 Lease 기반 Publish Snapshot Batch를 Claim해 service-db에 항목별 멱등 Upsert합니다.
8. Service Worker가 성공·재시도·최종 실패를 부분 성공 Batch ACK로 전달하고, Agent API가 항목별 상태와 이력을 갱신합니다.

## 스캐폴드 검증

```bash
uv run pytest
uv run python -m compileall -q app agent domain infrastructure workers scheduler mcp_server shared main.py
```
