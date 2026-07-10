# Bambi Agent API 프로젝트 구조

이 문서는 `agent-api-feature-spec.md`의 실제 기능 영역 1~43절을 코드 구조에 매핑한 결과입니다. 상세 API 필드, URL, 데이터 플로우는 명세에 정의되어 있지 않으므로 임의로 확정하지 않고 공통 계약과 라우터 경계만 만들었습니다.

## 스캐폴드 원칙

- 전체 기능 626개는 기능 ID를 소문자로 바꾼 비동기 함수와 1:1로 연결됩니다. 예: `BAMBI-009` → `bambi_009(...)`.
- 모든 기능 함수는 `FeatureRequest`를 받고 `FeatureResult`를 반환하며, 현재는 `NotImplementedError`를 발생시킵니다.
- 전용 MVP 범위 문서가 구현 우선순위의 기준입니다. 해당 47개 함수 바로 위에 `# MVP:` 주석을 붙였습니다.
- 전체 명세 44~46절의 MVP·2차·3차 항목은 기존 기능을 묶은 로드맵이므로 실행 함수를 중복 생성하지 않았습니다.
- API Request/Response 상세 필드가 확정되면 `app/schemas/`에 도메인별 Pydantic 모델을 추가하고, `app/routers/`의 라우터에서 기능 함수를 호출합니다.

## 최상위 구조

```text
bambi-agent-api/
├── app/                    # FastAPI 앱, 설정, 미들웨어, 라우터, 스키마
├── agent/                  # LangGraph 상태, 그래프, 노드, Tool, Prompt, Agent 기능
├── domain/                 # 사용자 컨텍스트, 개인 Wiki, 콘텐츠, Job, 발행 도메인
├── infrastructure/         # Provider, DB, Vector, Queue, Event, Source, Object Storage
├── workers/                # 작업 유형별 비동기 Worker 진입점
├── scheduler/              # 정기 작업 등록과 실행 진입점
├── mcp_server/             # MVP 이후 MCP Server와 Tool 경계
├── shared/                 # 공통 함수 계약과 비기능 정책
├── tests/                  # 명세-스캐폴드 정합성과 앱 조립 테스트
├── bench/                  # 실제 LLM 기능 구현 후 추가할 품질 벤치마크
└── docs/                   # 전체 기능 명세, MVP 범위, 구조 문서
```

## 기능 영역별 파일 매핑

| 절 | 기능 영역 | ID Prefix | 스캐폴드 파일 |
|---:|---|---|---|
| 1 | FastAPI 진입점 | `SYS` | `app/core/system_features.py` |
| 2 | 내부 API 인증 | `AUTH` | `app/security/internal_auth_features.py` |
| 3 | 사용자 컨텍스트 관리 | `CTX` | `domain/user_context/features.py` |
| 4 | 사용자 Wiki Source Event | `WSE` | `domain/personal_wiki/source_event_features.py` |
| 5 | User Personal LLM Wiki | `PWIKI` | `domain/personal_wiki/document_features.py` |
| 6 | 개인 Wiki Chunk 및 Embedding | `PWE` | `domain/personal_wiki/embedding_features.py` |
| 7 | 개인 Wiki 검색 및 RAG | `PRAG` | `domain/personal_wiki/retrieval_features.py` |
| 8 | 사용자 관심사 분류 | `INT` | `domain/interests/features.py` |
| 9 | Personal Wiki Builder Agent | `WBA` | `agent/wiki_builder/features.py` |
| 10 | Global Source 관리 | `GS` | `infrastructure/sources/management_features.py` |
| 11 | Global Source Collector | `COL` | `infrastructure/sources/collector_features.py` |
| 12 | Global Source 정제 및 저장 | `GSP` | `infrastructure/sources/processing_features.py` |
| 13 | Global Discovery 및 Trend | `DISC` | `agent/discovery/features.py` |
| 14 | LLM 공통 기능 | `LLM` | `agent/llm/features.py` |
| 15 | Prompt 관리 | `PROMPT` | `agent/prompts/features.py` |
| 16 | Model Config 관리 | `MODEL` | `agent/llm/model_config_features.py` |
| 17 | Retrieval 설정 관리 | `RET` | `agent/retrieval/features.py` |
| 18 | 콘텐츠 생성 에이전트 밤비 | `BAMBI` | `agent/bambi/features.py` |
| 19 | 생성 콘텐츠 유형 | `CTYPE` | `domain/content/type_features.py` |
| 20 | 플랜별 콘텐츠 차등화 | `PLAN` | `domain/content/plan_features.py` |
| 21 | 콘텐츠 품질 관리 | `QUALITY` | `agent/evaluation/quality_features.py` |
| 22 | 요약 기능 | `SUM` | `agent/summarization/features.py` |
| 23 | 번역 기능 | `TR` | `agent/translation/features.py` |
| 24 | 이미지 자료 생성 | `IMG` | `agent/images/features.py` |
| 25 | 추천 기능 | `REC` | `agent/recommendation/features.py` |
| 26 | Agent Job 관리 | `JOB` | `domain/jobs/features.py` |
| 27 | Agent Worker | `WORKER` | `workers/feature_workers.py` |
| 28 | Worker 공통 기능 | `WC` | `workers/common_features.py` |
| 29 | Scheduler | `SCH` | `scheduler/features.py` |
| 30 | Queue 및 Integration Event | `QUEUE/EVT` | `infrastructure/messaging/features.py` |
| 31 | Service API 연동 | `SVC` | `app/routers/service_features.py` |
| 32 | Service Worker 연동 | `SW` | `app/routers/service_worker_features.py` |
| 33 | 발행 콘텐츠 관리 | `PUB` | `domain/publishing/features.py` |
| 34 | 관리자 기능 | `ADMIN` | `app/routers/admin_features.py` |
| 35 | 자체 API Key | `KEY` | `app/security/api_key_features.py` |
| 36 | External Agent API | `EXT` | `app/routers/external_features.py` |
| 37 | MCP Server | `MCP` | `mcp_server/server_features.py` |
| 38 | MCP Tool | `MCPTOOL` | `mcp_server/tool_features.py` |
| 39 | Agent DB | `DB` | `infrastructure/persistence/features.py` |
| 40 | Object Storage | `OBJ` | `infrastructure/storage/features.py` |
| 41 | 로그 및 모니터링 | `OBS` | `infrastructure/observability/features.py` |
| 42 | 보안 및 개인정보 | `SEC` | `app/security/privacy_features.py` |
| 43 | 비기능 요구사항 | `NFR` | `shared/resilience_features.py` |

## MVP 구현 흐름

1. `app/routers/service_features.py`의 Service API 요청을 Job으로 변환합니다.
2. `workers/personal_wiki_builder.py`가 개인 Wiki 문서·Chunk·Embedding·관심사를 구성합니다.
3. `workers/global_source_collector.py`가 Naver, GDELT, NewsAPI Connector를 실행하고 정규화·중복 제거합니다.
4. `workers/bambi_generation.py`가 개인 Wiki와 Global Source 검색 결과로 콘텐츠를 생성합니다.
5. 생성 후보와 Citation을 저장하고 Content Ready 이벤트를 발행합니다.
6. Service Worker가 Publish Snapshot을 조회·저장한 뒤 ACK를 전달합니다.

## 스캐폴드 검증

```bash
uv run pytest
uv run python -m compileall -q app agent domain infrastructure workers scheduler mcp_server shared main.py
```
