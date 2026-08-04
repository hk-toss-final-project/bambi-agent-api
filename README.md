# Report Builder Agent API

이 저장소는 **서버 한 개**로 구성됩니다.

| | 파일 | 포트 | 제공 |
|---|---|---|---|
| **Agent API** | `app/main.py` | 8000 | API(`/internal/v1/**`) + LLM Wiki Graph UI + 키워드 비서 웹 UI(`/assistant/**`) |

MVP 핵심 파이프라인: 클리핑/URL → LLM Wiki → 관심사 → 외부 수집 → Report Builder 생성 → 발행 Snapshot.

키워드 비서(`agent/assistant`)의 실시간 수집·선별은 Report Builder의 `REPORT-005`(Global
Source 검색)·`REPORT-006`(생성 자료 선별)에 연결되어 있습니다. 웹 UI와 Main API가 **같은
수집·선별 코드**를 쓰므로 두 경로의 결과가 갈라지지 않습니다.

비서 UI는 루트가 아니라 `/assistant` 하위에만 노출합니다(루트는 API 서버의 것입니다).
UI가 필요 없는 배포에서는 `ENABLE_ASSISTANT_UI=false`로 끌 수 있습니다.

기능별 구현 상태는 [MVP 구현 현황 체크리스트](docs/agent-api-mvp-scope.md)에서 확인합니다.

## 실행 방법

### 0. 공통 준비

```bash
uv sync
cp .env.example .env
```

`.env`에서 최소한 아래 값을 채웁니다.

- **`AGENT_INTERNAL_TOKEN`** — `/internal/v1/**` 인증용. 아래처럼 생성한 값을
  Swagger의 `Authorize`와 Service API 호출에 사용합니다.

  ```bash
  openssl rand -hex 32
  ```

- **`OPENAI_API_KEY`** — Wiki 빌드·Report Builder 생성·키워드 비서 요약에 필요 (필수)
- `AGENT_DATABASE_URL`, `AGENT_DB_PASSWORD` — Agent API·Worker용.
  키워드 비서 UI만 쓸 경우 비워둬도 됩니다.
- `ENABLE_DEV_AGENT_API=true` — Swagger 개발 실행 API(`/internal/v1/dev/**`)
  활성화. 로컬 개발 시 권장합니다.

### 1. PostgreSQL 실행 (Agent API 선행 조건)

```bash
./scripts/start_agent_db.sh
```

처음 시작하는 DB뿐 아니라 이미 실행 중인 DB에도 미적용 Migration과 변경된
개발 Seed(`mock-clipping-user`, `28` 데이터 포함)를 반영한 뒤 Health 상태를 확인합니다.
자세한 절차는 [database/README.md](database/README.md)를 참고하세요. 키워드 비서
UI만 쓸 경우에는 필요 없습니다.

### 2. Agent API 서버 + Swagger

```bash
uv run uvicorn app.main:app --port 8000 --reload --loop app.main:selector_event_loop
```

- `--loop app.main:selector_event_loop`는 **DB 연결에 필요합니다.** Windows의
  uvicorn 기본 루프(ProactorEventLoop)에서는 psycopg 비동기 Pool이 붙지 못해
  DB를 쓰는 모든 요청이 `SERVICE_NOT_READY`로 실패합니다. Linux·macOS에서는
  Selector 루프가 기본이라 동작이 달라지지 않으므로 그대로 두면 됩니다.
- Swagger UI: <http://127.0.0.1:8000/docs> — 우측 상단 버튼으로 다크·라이트
  모드를 전환할 수 있고, 선택한 테마는 브라우저에 저장됩니다.
- ReDoc: <http://127.0.0.1:8000/redoc> · OpenAPI JSON: <http://127.0.0.1:8000/openapi.json>
- `APP_ENV=local`(또는 `test`) + `ENABLE_DEV_AGENT_API=true`면 `dev-*` 태그의
  개발 실행 API가 함께 등록됩니다. 엔드포인트별 계약은
  [FastAPI MVP API 설계](docs/fastapi-mvp-api.md)를 참고하세요.
- 에이전트 그래프 구조 시각화: <http://127.0.0.1:8000/dev/graphs> —
  Personal Wiki·Report Generation·키워드 비서 그래프를 Mermaid 차트로
  보여줍니다(개발 API와 같은 플래그로 활성화).
- Swagger UI와 개발 시각화 페이지는 토큰 없이 열 수 있지만,
  `/internal/v1/**` 실행에는 `AGENT_INTERNAL_TOKEN` Bearer 인증이 필요합니다.
  Swagger의 `Authorize`에 토큰을 한 번 입력하면 브라우저에 유지되어 이후
  요청에 자동으로 추가됩니다.
  문서가 필요 없는 환경에서는 `DOCS_ENABLED=false`로 비활성화할 수 있습니다.

### 3. LLM Wiki Graph UI

Agent API 서버(8000)에 내장된 개인 지식 그래프 시각화 페이지입니다.

```text
http://127.0.0.1:8000/wiki-graph?user_id={user_id}
예) http://127.0.0.1:8000/wiki-graph?user_id=28   ← 개발 Seed 사용자
```

- Entity(초록)·Concept(보라) Node 그래프, 검색·종류 필터, 확대·이동·Node
  Drag와 Markdown 상세 보기를 제공합니다.
- PostgreSQL이 필요하며, Wiki가 생성된 사용자만 그래프가 표시됩니다.
- HTML 화면 자체는 인증 없이 열리지만, Graph 데이터는
  `GET /internal/v1/users/{user_id}/wiki/graph`에서 읽으므로 Bearer 인증이
  필요합니다. 실제 서비스 화면도 같은 JSON API를 소비합니다
  ([Service 연동 가이드](docs/service-integration-guide.md) §3.6).
- 서버 `.env`의 토큰은 브라우저로 자동 전달되지 않습니다. `/docs`의
  `Authorize`에 `AGENT_INTERNAL_TOKEN` 값만(`Bearer ` 접두어 제외) 입력한 뒤
  같은 Origin의 `/wiki-graph`를 열면 저장된 `InternalBearer` 인증을 재사용합니다.
  Swagger를 거치지 않았다면 Graph 화면의 인증란에 같은 값을 한 번 입력하면 됩니다.
- Graph 화면도 Swagger의 `persistAuthorization`과 마찬가지로 개발 편의를 위해
  토큰을 브라우저 `localStorage`에 저장합니다. 공유 PC에서는 사용하지 말고,
  `localhost`와 `127.0.0.1`은 서로 다른 Origin이므로 두 화면의 호스트를 동일하게
  맞춰야 합니다.

### 4. 키워드 비서 웹 UI

키워드를 입력하면 관련 YouTube 영상 자막, Reddit 게시글을 LLM으로 요약하고, 최근
뉴스 기사를 중복 없이 모아 브리핑으로 보여줍니다. 처음 조회하는 키워드는 폭넓게
보여주고, 이미 본 영상은 다음부터 제외합니다.

**API 서버와 같은 프로세스**에서 제공되므로 따로 띄우지 않습니다.

```bash
# 위 2번에서 띄운 서버 그대로 사용
# 브라우저에서 http://localhost:8000/assistant/ 접속
```

이 화면은 PostgreSQL 없이 동작하며 `OPENAI_API_KEY`만 필요합니다. DB 연결에 실패해도
서버는 기동하고 비서 UI는 그대로 쓸 수 있습니다(DB가 필요한 API만 `503
SERVICE_NOT_READY`로 응답합니다). 분해 전 구조와 설계 배경은
[보관된 에이전트 구조 문서](docs/archive/2026-07/agent-structure-and-collection-loop.md)를 참고하세요.

### 5. Worker 실행

등록된 Agent Job(Wiki 빌드, Report Builder 생성)과 외부 수집을 처리하는 CLI입니다.
Wiki 빌드와 Report Builder 생성은 OpenAI를 실제 호출하므로 비용이 발생합니다.

| Worker | 용도 | 모드 |
|---|---|---|
| `url-collection` | 사용자 URL을 Jina Reader로 읽어 Markdown 원문 Version 저장 | 단발 / `--loop` 상주 |
| `personal-wiki` | 클리핑·URL 원본을 LLM Wiki로 빌드 (Chunk 포함, Embedding은 보류) | 단발 / `--loop` 상주 |
| `report-generation` | 생성 Job을 처리해 콘텐츠·발행 Snapshot 저장 | 단발 / `--loop` 상주 |
| `global-collector` | 키워드로 외부 기사 수집 (`--keywords` 필수, Provider 기본 `gdelt,naver,google_news`) | 단발 |
| `global-content` | 수집된 기사의 본문 확보 | 단발 |

```bash
# 단발: 대기 Job 한 Batch를 처리하고 종료
uv run python -m workers.main --worker url-collection
uv run python -m workers.main --worker personal-wiki
uv run python -m workers.main --worker report-generation

# 상주: Job이 생기면 자동 처리 (없으면 60초 간격으로 확인)
uv run python -m workers.main --worker url-collection --loop --interval-seconds 5
uv run python -m workers.main --worker personal-wiki --loop
uv run python -m workers.main --worker report-generation --loop

# 외부 기사 수집 → 본문 확보
uv run python -m workers.main --worker global-collector --keywords "AI 에이전트,개인화"
uv run python -m workers.main --worker global-content
```

`--limit`, `--lease-seconds`, `--model`, `--interval-seconds`(상주 모드) 옵션으로
Batch 크기와 실행을 조정합니다. 상주 Worker는 `scheduled_at`이 도래한 Job만
Claim하므로 예약 생성 요청은 지정 시각에 처리됩니다.

URL 등록 API는 URL Head와 `personal_wiki_url` Job을 먼저 Commit하고 202를
반환합니다. `url-collection` 상주 Worker가 Job을 감지하면 Jina Reader로 본문을
읽어 `user_source_document_versions.raw_content`에 Markdown으로 저장하고, 본문이
변경된 경우 `personal_wiki_build` Job을 등록합니다. 따라서 운영 환경에서는
`url-collection`과 `personal-wiki` Worker를 함께 실행해야 합니다.

### 6. 정기 수집 Scheduler

Global 풀을 채우는 정기 수집(SCH-001·SCH-002·SCH-003·SCH-004)입니다. **API 서버를 띄우면
같이 돕니다** — 별도 실행이 필요 없습니다. 기동 시 백그라운드 Task로 올라가
tick(기본 60초)마다 실행 차례가 된 Source만 수집합니다.

> **시계는 한 벌만 돌아야 합니다.** API를 여러 인스턴스로 띄우면 같은 수집이
> 인스턴스 수만큼 중복 실행됩니다. 그런 배포에서는 `ENABLE_COLLECTION_SCHEDULER=false`로
> 서버 내장 Scheduler를 끄고, 아래 CLI를 한 벌만 띄우세요.

```bash
# 상주 (서버 내장 Scheduler를 끈 배포용)
uv run python -m scheduler.main

# 단발: 지금 판정 결과만 확인 (실행 차례가 아니면 사유를 출력)
uv run python -m scheduler.main --once
```

#### 스케줄 설정 — Service API로 조정

수집 주기·키워드는 코드가 아니라 `agent.global_sources` row가 소유합니다.
Service는 아래 엔드포인트로 이 값을 바꾸고, 변경은 **다음 tick부터 반영**됩니다
(서버 재시작 불필요).

| 엔드포인트 | 기능 |
|---|---|
| `GET /internal/v1/collection-schedules` | 현재 설정 + 최근 실행 이력 (SCH-022) |
| `POST /internal/v1/collection-schedules` | 등록 (멱등 Upsert, SCH-017) |
| `PATCH /internal/v1/collection-schedules/{source_key}` | 주기·키워드 수정 (SCH-018) |
| `POST .../{source_key}/pause` | 중지 — 설정은 보존 (SCH-019) |
| `POST .../{source_key}/resume` | 재개 (SCH-020) |

```bash
curl -X POST http://localhost:8000/internal/v1/collection-schedules \
  -H "Authorization: Bearer ${AGENT_INTERNAL_TOKEN}" \
  -H "Content-Type: application/json" \
  -d '{"source_key":"latest-naver","provider":"naver","schedule_cron":"0 */6 * * *",
       "keywords":["AI 에이전트","개인화"],"language":"ko","daily_max_runs":12}'
```

| 설정 | 뜻 | 없을 때 |
|---|---|---|
| `schedule_cron` | 수집 주기 (Cron 식, UTC) | 비어 있으면 Scheduler가 무시 |
| `keywords` | 수집할 주제 목록 | 비어 있으면 건너뛰고 사유 출력 |
| `daily_max_runs` | 하루 최대 실행 횟수 | 제한 없음 |
| `limit_per_provider` | 한 번에 수집할 기사 수 | 10건 |

Provider는 `naver`·`google_news`·`gdelt`·`newsapi` 넷을 지원합니다. 한국어 주제는
`naver`, 영문 주제는 `google_news`가 정확합니다(실측: 'Cloudflare' 수집 시 Naver는
10건 중 관련 3건, google_news는 5건 전부 관련).

| Provider | 알아둘 점 |
|---|---|
| `naver` | 자격 증명 필요 (`NAVER_CLIENT_ID`·`NAVER_CLIENT_SECRET`). 일 25,000회 |
| `google_news` | 자격 증명 불필요. 원본 URL 디코딩 때문에 키워드당 12초쯤 더 걸림 |
| `gdelt` | 자격 증명 불필요. **짧은 간격으로 반복 호출하면 429** — 정기 주기에서는 정상 |
| `newsapi` | `NEWS_API_KEY` 없으면 등록해도 안 돎. 무료 플랜 일 100회 |

`gdelt`는 인증 없는 공개 API라 연속 호출을 제한합니다. 6시간 주기로 도는 스케줄에서는
문제가 없지만, `--once --force`로 수동 점검을 몇 분 간격으로 반복하면 429가 납니다.
그때도 실패는 Provider 단위로 격리되어 나머지 수집은 그대로 완료됩니다.

**키워드는 각각 따로 검색합니다.** `["코스피","삼성전자"]`는 두 번의 개별 질의가
됩니다. 하나의 문자열로 합치면(`"코스피 삼성전자"`) 두 단어를 모두 포함하는 기사만
찾아 0건이 나옵니다. `daily_max_runs`는 이 개별 실행(= 외부 API 호출) 수를 셉니다.

NewsAPI 무료 플랜은 하루 100회가 한계이므로 `daily_max_runs`를 반드시 함께
설정하세요. `--once --force`는 Cron 실행 시각만 건너뛰고 호출 한도는 지킵니다.

수집된 기사는 본문 없는 `pending` 상태로 쌓이므로, `global-content` Worker도
함께 돌려야 Jina Reader가 본문을 채웁니다.

## 리포트 생성 에이전트

리포트 생성 그래프에는 **도구를 직접 쓰는 에이전트 둘**이 들어 있습니다. 어떤
도구를 몇 번 부를지는 코드가 정하지 않고 LLM이 관찰 결과를 보며 정합니다.

```
research → load_context → generate → review → persist
   ▲                          ▲         ┊
   │                          └─────────┘
조사원                     검토자가 사실관계 문제를 찾으면
                           재작성 (최대 1회)
```

| 노드 | 역할 | 도구 |
|---|---|---|
| `research` | **조사원** — 근거 자료를 모은다 | `search_pool` |
| `review` | **검토자** — 인용을 원문과 대조한다 | `get_source` · `search_pool` |

**검토자에게는 초안과 근거 "제목만" 주고 원문은 주지 않습니다.** 확인하려면
`get_source`로 직접 꺼내야 하므로, 어떤 인용을 몇 개나 대조할지 검토자가
스스로 정하게 됩니다.

판단만 LLM에게 맡기고 **셈과 컷오프는 코드에 남겼습니다.** 예를 들어 "어떤
검색어로 찾을까"는 조사원이 정하지만 "근거가 충분한가"는
`is_pool_sufficient`가 셉니다 — LLM에게 셈을 맡겼을 때 판단 정확도가 80%에
머물렀고, 프롬프트를 두 번 고쳐도 오류 방향만 바뀌었기 때문입니다.

둘 다 환경변수로 끌 수 있습니다(`RESEARCH_AGENT_ENABLED=0`,
`CRITIC_ENABLED=0`). 꺼도 리포트 생성은 기존 고정 경로로 계속됩니다.

### 측정된 품질

프롬프트·모델을 바꾸면 단위 테스트는 그대로 통과하지만 품질은 조용히
달라집니다. 그래서 LLM 판단이 들어가는 기능은 [`bench/`](bench/README.md)에서
실제 LLM로 측정합니다. 아래는 2026-08-04 기준이며, 실행 기록은 각
`results/` 디렉터리에 있습니다.

**검토자** — 근거에 없는 서술을 잡아내는가 ([30케이스](bench/critic/dataset.jsonl))

| 지표 | 값 | 뜻 |
|---|---|---|
| 거짓 탐지율 | 93.3% | 지어낸 초안 15건 중 잡아낸 비율 |
| 헛지적률 | 0.0% | 정상 초안 15건 중 잘못 되돌린 비율 |
| 비용 | 약 $0.02 / 30건 | 리포트당 도구 호출 1.5회 |

**조사원** — 주제어만으로는 안 나오는 자료를 찾아내는가 ([15케이스](bench/researcher/dataset.jsonl))

| 지표 | 값 | 뜻 |
|---|---|---|
| 확장 도달률 | 100% | 연관어로 넓혀야 닿는 자료 13건 중 찾은 비율 |
| 실시간 수집 판단 | 100% | 인터넷 수집을 불러야 할 때만 불렀는가 |
| 잡음 유입 | 0건 | 주제와 무관한 자료를 끌어온 케이스 수 |

**모델 선택** — 같은 데이터셋으로 위·아래 모델을 재고 `gpt-4.1-mini`를
유지하기로 했습니다 ([상세](bench/critic/results/2026-08-04_model-comparison.md)).

| 모델 | 정확도 | 헛지적률 | 입력 토큰 |
|---|---|---|---|
| `gpt-4.1` | 100% | 0.0% | 49,876 |
| **`gpt-4.1-mini`** | **96.7%** | **0.0%** | **39,696** |
| `gpt-4.1-nano` | 80.0% | 13.3% | 46,406 |

`gpt-4.1`이 더 잡는 것은 경계 케이스 1건뿐이라 비용 차이를 감수할 근거가
부족했고, `nano`는 멀쩡한 리포트를 8건 중 1건꼴로 되돌려 쓸 수 없었습니다.

> 프롬프트를 고쳐 품질을 올리려는 시도는 지금까지 네 번 중 한 번만
> 성공했습니다. 실패한 시도도 결과 문서에 그대로 남겨 두었습니다 —
> 같은 길을 다시 가지 않기 위해서입니다.

## 구조

Agent API는 전체 기능 명세 1~43절의 기능 ID를 코드 함수와 1:1로 매핑하고,
전용 MVP 문서의 구현 대상 함수 위에 `# MVP:` 주석을 표시합니다. 각 기능
영역의 `api.py`는 공개 facade로만 사용하며, 실제 구현은 `features/` 패키지에
역할별로 분리되어 있습니다.

## Agent API 문서

- [문서 안내와 현행·보관 기준](docs/README.md)
- [전체 기능 명세](docs/agent-api-feature-spec.md)
- [MVP 개발 범위와 구현 현황 체크리스트](docs/agent-api-mvp-scope.md)
- [FastAPI MVP API 설계](docs/fastapi-mvp-api.md)
- [Service 연동 가이드 (service-api·service-worker)](docs/service-integration-guide.md)
- [Agent DB 설계](docs/agent-db-design.md)
- [Agent DB 테이블 카탈로그](docs/agent-db-table-catalog.md)
- [Agent DB 컬럼 사전](docs/agent-db-column-dictionary.md)
- [프로젝트 구조와 기능 파일 매핑](docs/project-structure.md)

## 검증

```bash
uv run pytest
uv run python -m compileall -q app agent domain infrastructure workers scheduler mcp_server shared main.py
```

`pytest`는 **LLM을 호출하지 않습니다.** 항상 무료·빠르게·같은 결과로 통과해야
하므로 LLM이 필요한 부분은 mock으로 대체합니다.

LLM 판단 품질은 별도로 측정합니다. 비용이 발생하므로 `--confirm-cost` 없이는
실행되지 않습니다.

```bash
# 예상 케이스 수와 토큰만 출력하고 종료
uv run python bench/critic/run.py

# 실제 실행 (약 $0.02)
uv run python bench/critic/run.py --confirm-cost

# 다른 모델로 비교
uv run python bench/critic/run.py --model gpt-4.1 --confirm-cost
```

프롬프트·모델·파라미터를 바꿨다면 **벤치마크를 다시 돌려 결과를 기록한 뒤**
개선 여부를 판단합니다. 자세한 규칙은 [`bench/README.md`](bench/README.md)와
`AGENTS.md`의 "8. LLM 기능 벤치마크"를 따릅니다.
