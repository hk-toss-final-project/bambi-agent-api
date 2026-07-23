# 키워드 비서 AI — 개발 명세

> 이 문서는 프로젝트의 새 방향인 "키워드 → 관련 URL/영상 수집·요약 비서"의 명세입니다.
> 기존 `agent-api-feature-spec.md` / `agent-api-mvp-scope.md`의 대형 리포트 생성기 에이전트
> 명세는 이 방향으로 재편 중이며, 관련 스캐폴드는 단계적으로 정리합니다.

## 목표

키워드를 입력하면 다음을 한 화면에서 제공한다.

1. **YouTube 요약**: 키워드로 관련 영상을 검색하고, 각 영상의 자막을 LLM으로 요약한다.
2. **최신 기사 URL**: RSS(Google News 검색 피드)로 최신 기사를 모으고, Jina Reader로
   본문을 정제한 뒤, URL·제목 기준으로 중복을 제거해 제공한다.

## 구성

구현은 모두 `agent/assistant/features/` 아래에 두고, 외부 계층(웹 등)은
[agent/assistant/api.py](../agent/assistant/api.py) facade만 import한다
(AGENTS.md의 "구현은 features/, 공개는 api.py" 규칙). 이 기능 영역은 전체 명세
1~43절의 기능 ID 체계(REPORT-* 등)에 속하지 않는 별도 제품 라인이라 기능 ID를
부여하지 않는다.

| 영역 | 파일 | 역할 |
|---|---|---|
| 공개 facade | [api.py](../agent/assistant/api.py) | `assist`·`assist_daily`·`assist_daily_agent` 노출 |
| YouTube | [features/youtube.py](../agent/assistant/features/youtube.py) | 검색(youtube-search-python), 자막(youtube-transcript-api), 자막 요약 |
| RSS·Jina | [features/feeds.py](../agent/assistant/features/feeds.py) | Google News RSS 조회, Jina Reader 정제, 최신순 정렬 + 중복 제거 |
| Reddit | [features/reddit.py](../agent/assistant/features/reddit.py) | search.rss 조회(레이트리밋 대응), 게시글 요약 |
| 날짜 추출 | [features/dates.py](../agent/assistant/features/dates.py) | pubDate → 메타태그 → URL 패턴 → 본문 파싱 → first_seen 폴백 |
| 스코어링 | [features/scoring.py](../agent/assistant/features/scoring.py) | 유사도 × 신선도 × 소스가중 × 클러스터부스트 |
| 클러스터링 | [features/clustering.py](../agent/assistant/features/clustering.py) | 임베딩 그리디 묶기(멤버 전체 비교) |
| 중복 제거 | [features/dedup.py](../agent/assistant/features/dedup.py) | 최근 7일 보고 임베딩 대비 신규/중복/업데이트 판정 |
| 원인 분류 | [features/outcomes.py](../agent/assistant/features/outcomes.py) | 결과 빈약 원인을 구조화(재시도 판단 근거) |
| 선별 파이프라인 | [features/pipeline.py](../agent/assistant/features/pipeline.py) | 수집→선별→통합요약 (결정론) |
| 리서치 에이전트 | [features/graph.py](../agent/assistant/features/graph.py) | LangGraph 단일 그래프(검색어 재구성 루프) |
| 보고서 | [features/report.py](../agent/assistant/features/report.py) | 워터폴(당일/주간/개념 정리) Markdown 생성 |
| 요약 | [features/summarize.py](../agent/assistant/features/summarize.py) | ChatOpenAI 기반 한국어 요약 헬퍼 |
| 오케스트레이션 | [features/service.py](../agent/assistant/features/service.py) | 진입점 3종 결합 (소스별 실패 격리) |
| 웹 | [app/assistant/web.py](../app/assistant/web.py) | `/assistant/` 키워드 폼, `/assistant/search` 결과 페이지 |

## 사용 라이브러리

- `youtube-search-python` — 검색 (API 키 불필요). httpx 0.28에서 `proxies` 인자 제거로
  깨지므로 `httpx>=0.27,<0.28`로 고정한다.
- `youtube-transcript-api` (v1.x) — `YouTubeTranscriptApi().fetch(video_id, languages=...)`.
- `feedparser` — RSS 파싱.
- `httpx` — Jina Reader(`https://r.jina.ai/<url>`) 호출.

## 외부 호출과 비용

- YouTube 검색·자막, Google News RSS, Jina Reader는 외부 서비스 호출이다.
- 자막 요약은 OpenAI(`gpt-4.1-mini` 기본)를 호출하므로 비용이 발생한다. `OPENAI_API_KEY`가
  `.env`에 필요하다.
- Jina Reader는 대상 URL을 외부 서비스로 전송해 본문을 추출한다.

## 실행

키워드 비서 웹 UI는 **Agent API 서버와 같은 프로세스**에서 제공된다.

```bash
uv run uvicorn app.main:app --port 8000 --loop app.main:selector_event_loop
```

- 키워드 비서 UI : <http://127.0.0.1:8000/assistant/>  ← 브라우저로 접속해 키워드 입력
- API 문서       : <http://127.0.0.1:8000/redoc>

비서 UI는 `/assistant` 하위에만 노출한다 — 이 저장소는 API 서버이므로 루트를
사람이 보는 화면이 차지하면 안 된다. UI가 필요 없는 배포에서는
`ENABLE_ASSISTANT_UI=false`로 등록을 끌 수 있다
(비서 의존성도 로드하지 않는다).

> **이력**: 한때 API 서버(8000)와 비서 UI(8100)를 별도 프로세스로 분리했다.
> 이후 Report Builder가 비서의 수집·선별을 그대로 쓰도록 코드 경로를 통합하면서
> (`REPORT-005`·`REPORT-006`), 서버 프로세스도 하나로 되돌렸다. 두 실행 경로가
> 같은 코드를 쓰는 것이 이 통합의 목적이다.

## Report Builder와의 연결

Main Swagger로 들어오는 콘텐츠 생성(Job → Worker → `build_report_generation_graph`)은
이 비서의 수집·선별을 **호출**한다. 로직을 복사하지 않으므로 두 파이프라인이 갈라지지
않는다.

```
report_004  개인 Wiki 검색      (DB에 저장된 사용자 문서)
   ↓
report_005  Global Source 검색  ← agent/assistant 실시간 수집 (뉴스 RSS·YouTube·Reddit)
   ↓                              collect_live_context()
report_006  생성 자료 선별      ← 개인 Wiki 맥락 + 실시간 근거 병합·상한 적용
   ↓                              select_generation_context()
report_012  개인화 → report_008/009 생성 → report_011 인용 → report_018 저장
```

어댑터는 [agent/report_builder/features/live_sources.py](../agent/report_builder/features/live_sources.py)에 있다.

> **보정 전 상태**: `REPORT-005`는 개인 Wiki 결과를 그대로 흘려보내는 패스스루였고
> `REPORT-006`은 미구현이었다. 그래서 Main API 생성은 DB에 이미 저장된 문서만 근거로
> 삼았고, 비서의 최신성·관련도·중복 제거 판단을 전혀 거치지 않았다.

수집 실패는 생성을 막지 않는다. 실시간 자료를 못 얻으면 경고 로그를 남기고 개인 Wiki
근거만으로 생성한다.

## 이력 저장소 (2026-07-22 DB 이전)

비서는 개인화를 위해 "이 사용자에게 무엇을 이미 보여줬는지"를 기억한다. 저장 위치는
[features/storage.py](../agent/assistant/features/storage.py)가 정한다.

| 이력 | 테이블 | 용도 |
|---|---|---|
| 수집 | `agent.assistant_collected_documents` | 같은 URL 재수집 방지, `first_seen`(발행일 대용), 주간 폴백용 점수 |
| 보고 기사 | `agent.assistant_reported_articles` | 같은 기사가 다음 리포트에 반복되는 것 방지 |
| 시청 | `agent.assistant_watched_videos` | 실제로 클릭한 영상만 기록(단순 노출 제외) |
| 보고 임베딩 | `agent.assistant_report_embeddings` | 최근 7일 보고분과 유사도 비교(`vector(1536)`) |

### 백엔드 선택

1. `AGENT_DATABASE_URL`이 있고 연결되면 → **PostgreSQL**
2. 설정이 없으면 → 로컬 JSON (`DATA_DIR`, 로컬 개발용)
3. 설정은 있는데 연결 실패면 → 경고 로그 + 로컬 JSON 폴백

3번을 두는 이유: 비서는 PostgreSQL 없이도 동작하던 제품이고, DB 장애로 화면 전체가
멈추는 것보다 이력이 로컬에 쌓이는 편이 낫다고 판단했다. 어떤 백엔드를 쓰는지는 기동 시
로그로 남긴다.

`history.py`·`dedup.py`의 공개 함수 시그니처는 그대로라 호출부는 저장 위치를 모른다.

> **이전 상태(문제)**: `data/*.json`에 저장했다. 서버를 여러 대로 늘릴 수 없고, 재배포
> 시 유실되며, 파일 전체를 읽고 통째로 덮어써서 동시 요청에 이력이 유실될 수 있었다.
> 임베딩은 1.6MB 전체를 읽어 파이썬에서 코사인을 계산했지만, 지금은 최근 N일 행만 DB가
> 골라 준다.

> **경로 버그**: facade 마이그레이션으로 `config.py`가 `features/` 아래로 내려가면서
> `DATA_DIR`의 상대 경로가 한 단계 밀려 `agent/data/`를 가리켰고, 이력이 `data/`와
> `agent/data/` 두 곳으로 쪼개졌다. 경로를 저장소 루트 기준으로 바로잡고 회귀 테스트
> (`test_data_dir_points_to_repository_root`)로 고정했다. 두 위치의 이력은 모두 DB로
> 이관했다(1,512건 → 중복 병합 후 1,508행).

### 기존 JSON 이력 이관

```bash
uv run python scripts/migrate_assistant_history.py --dry-run   # 건수만 확인
uv run python scripts/migrate_assistant_history.py             # 실제 이관
uv run python scripts/migrate_assistant_history.py --data-dir agent/data
```

멱등하므로 여러 번 실행해도 안전하다. 원본 JSON은 지우지 않는다.

## 선별 파이프라인의 임계값 (2026-07-20 보정)

[pipeline.py](../agent/assistant/features/pipeline.py)는 수집한 문서를 유사도 필터 → 클러스터링 →
스코어링 → 중복 검사 → 발행 판정 순으로 거른다. 이 중 **두 임계값은 고정값이 아니라
"절대 하한 + 상대 비율" 하이브리드**를 쓴다. 설정은 [config.py](../agent/assistant/features/config.py)에 있다.

```
유사도 컷 = max(SIMILARITY_FLOOR 0.25, 이번 실행 최고 유사도 × SIMILARITY_RATIO 0.75)
발행   컷 = max(PUBLISH_FLOOR   0.05, 이번 실행 최고 점수   × PUBLISH_RATIO   0.50)
```

### 왜 고정값을 쓰지 않는가

짧은 키워드와 긴 문서의 코사인 유사도(text-embedding-3-small)는 0.3~0.5대에 형성되고,
그 분포가 키워드마다 다르다. 실측:

| 키워드 | 최대 유사도 | 0.40 고정 컷 적용 시 통과 |
|---|---|---|
| 코스피 | 0.475 | 16건 |
| 전고체 배터리 | 0.520 | 9건 |
| 커피 | 0.494 | 1건 |
| 인공지능 반도체 수출 규제 | 0.412 | 1건 |

키워드가 길고 구체적일수록 임베딩이 분산돼 유사도 절댓값이 내려간다. 따라서 고정값
하나로는 어떤 키워드를 반드시 굶긴다. 상대 비율이 이 스케일 차이를 흡수하고,
절대 하한이 "수집 결과가 통째로 무관한 경우"를 막는다.

> **보정 전 상태(버그)**: `MIN_SIMILARITY=0.6`, `PUBLISH_THRESHOLD=0.5` 고정이었다.
> 실측 최고 유사도가 0.476이라 유사도 필터에서 관련 문서 33건이 **전부** 탈락했고,
> 점수 이론상 최대도 0.357이라 발행 컷에 닿을 수 없었다. 결과적으로 항상 0건이 선정돼
> 근거 없는 폴백 경로로 빠졌다.

### 클러스터링 (같은 사건 묶기)

`CLUSTER_SIM_THRESHOLD = 0.65` — 여기는 상대값이 아니라 **절대값**을 쓴다. "이 둘이
같은 사건인가"는 키워드와 무관한 판단이고, 문서 대 문서(둘 다 긴 글) 비교라 키워드 대
문서처럼 스케일이 흔들리지 않기 때문이다.

실측('코스피' 뉴스 26건, 문서쌍 325개): 최대 0.737 / 중앙 0.433. 같은 사건을 다룬
기사쌍은 0.68~0.74에 몰렸고, 0.60 아래로 내리면 서로 다른 이슈가 섞였다.

[clustering.greedy_clusters](../agent/assistant/features/clustering.py)는 클러스터의 **어느
멤버와든** 기준을 넘으면 편입한다(시드 문서와만 비교하지 않는다). 같은 사건 기사라도
표현 차이로 A-B 0.70, B-C 0.70인데 A-C 0.60인 경우가 흔해, 시드 비교로는 같은 사건이
여러 클러스터로 쪼개지기 때문이다.

> **보정 전 상태(버그)**: 기본값이 0.8이었는데 실측 문서쌍 최댓값이 0.737이라
> **어떤 문서도 병합되지 않았다**(26건 → 26개 클러스터, 전부 크기 1). 같은 사건을 다룬
> 기사들이 각각 별개 아이템으로 보고서에 중복 노출됐고, `cluster_boost`도 항상 1.0이라
> "여러 매체가 동시에 다룬 이슈"라는 신호가 점수에 반영되지 않았다.

### 소스 신뢰도는 원본 발행처로 판정한다

Google News RSS의 `link`는 리다이렉트 주소(`news.google.com/rss/articles/...`)라서,
도메인만 보면 모든 기사가 `news.google.com`이 된다. 그러면 `SOURCE_WEIGHTS` 테이블이
한 건도 매칭되지 않아 전부 기본 가중치(0.5)를 받는다.

RSS가 원본 발행처를 `<source url="https://www.chosun.com" title="조선일보">`로 따로 주므로,
[feeds.\_extract\_source](../agent/assistant/features/feeds.py)로 이를 뽑아 `source_url`에 담고
[scoring.score_document](../agent/assistant/features/scoring.py)가 그 값으로 가중치를 조회한다.
**추가 HTTP 요청이 필요 없다.**

### 근거가 없으면 생성하지 않는다

수집·선별 결과가 0건이면(`mode="evergreen"`) 보고서 본문을 **생성하지 않는다**. 이전에는
이 경로에서 LLM이 모델 내부 지식으로 본문을 썼는데, 출처 없는 내용이 근거 기반 브리핑과
똑같은 모양으로 나가 사용자가 사실로 오인할 위험이 있었다. 지금은 LLM을 호출하지 않고
"참고할 문서를 수집하지 못했다"고 명시한다.

## 리서치 에이전트 (LangGraph 단일 그래프)

[features/graph.py](../agent/assistant/features/graph.py)는 위 결정론 파이프라인을
도구처럼 감싸고, 그 위에 얇은 에이전트 레이어만 얹는다. 스코어링·클러스터링·중복
판정 같은 수치 판단은 LLM에 맡기지 않는다.

```
START → plan(토픽을 1차 검색어로)
      → select(run_daily 실행 + 원인 분류 + 재시도 판단)
      → (조건부) 재구성 가능 원인 & 한도 남음? → reformulate : write_report
      → reformulate(LLM이 새 검색어 제안)
      → (조건부) 쓸 만한 새 검색어를 얻었나? → select(루프) : write_report
      → write_report → END
```

### 재시도는 "검색어로 고칠 수 있는 원인"일 때만 한다

[features/outcomes.py](../agent/assistant/features/outcomes.py)가 결과를 아래로 분류하고,
`no_results`·`low_relevance`일 때만 재구성한다.

| 원인 | 의미 | 재구성 |
|---|---|---|
| `success` | 당일 신규 아이템 확보 | 불필요 |
| `provider_failure` | 뉴스·YouTube·Reddit 또는 임베딩 장애 | **금지** |
| `no_results` | 수집 0건 또는 기초 필터 전멸 | 수행 |
| `low_relevance` | 유사도 필터 전멸 | 수행 |
| `duplicate_only` | 최근 보고서에 이미 실은 소식뿐 | **금지** |
| `below_threshold` | 관련 문서는 있으나 점수 미달 | **금지** |

원인을 보지 않고 "아이템 없음"만으로 재시도하면, 전체 소스가 타임아웃인 상황에서도
파이프라인 3회 + 재구성 LLM 2회를 실행해 **비용만 최대 3배**로 늘고 결과는 그대로다.
판정은 문자열 에러 메시지를 파싱하지 않고 `log`의 구조화 필드(`source_failures`,
`embedding_failed`, 단계별 잔존 건수, `exclusions`)만 본다.

### 같은 검색어로 두 번 수집하지 않는다

LLM이 빈 값·이미 시도한 검색어·너무 긴 문자열(`MAX_QUERY_CHARS` 40자 초과)을 주거나
호출 자체가 실패하면, 토픽으로 되돌려 재실행하지 않고 **재구성 실패로 종료**해 그 시점
결과로 보고서를 쓴다. 같은 검색어 재실행은 결과가 동일함이 보장된 순수 비용이다.

### 추적(trace)은 구조화 이벤트로 남긴다

각 노드는 `{node, status, reason, query, errors, duration_ms, message}` 이벤트를 쌓는다.
시도별 오류도 마지막 시도 것만 남기지 않고 전부 누적하며(`[N차 시도]` 접두),
보고서 생성이 실패하거나 본문이 비면 `status="failed"`로 기록한다. 이 이벤트는
웹 결과 페이지의 "⓪ 에이전트 판단 과정" 섹션에 그대로 노출된다.

## 테스트

- [tests/agent/assistant/](../tests/agent/assistant/) — 검색/자막/요약/피드/중복 제거/오케스트레이션을
  네트워크·LLM 호출 없이 mock으로 검증한다. `uv run pytest`는 무료·결정적으로 통과한다.
- 임계값 관련 회귀 테스트: `test_scoring.py`(컷 계산·소스 가중치),
  `test_pipeline.py`(키워드 스케일 적응·하한 동작·콜드 스타트),
  `test_report_daily.py`(근거 0건일 때 LLM 미호출).
- 에이전트 회귀 테스트: `test_outcomes.py`(원인 분류),
  `test_agent_graph.py`(장애 시 재시도 금지, 중복·과장 제안 시 재검색 금지,
  시도별 오류 누적, 구조화 trace).

## 벤치마크 (LLM 품질)

검색어 재구성은 LLM 프롬프트라 단위 테스트로 품질을 보장할 수 없어
[bench/assistant_reformulation/](../bench/assistant_reformulation/)에 별도로 둔다.
그래프와 같은 프롬프트를 쓰도록 `graph.REFORMULATE_SYSTEM`과
`build_reformulate_prompt`를 직접 import한다.

```bash
uv run python bench/assistant_reformulation/run.py \
    --input-cost-per-million 0.4 --output-cost-per-million 1.6
```

채점은 LLM 심판 없이 결정론적 규칙으로 한다: 비어 있지 않을 것, 이미 시도한 검색어와
다를 것, 길이 상한 이내일 것, 주제 앵커 용어를 포함할 것.

| Prompt 버전 | 정확도 | 비고 |
|---|---|---|
| `ff7d880+a9799614fae3` | 14/15 (93.3%) | 길이 제약 없던 기준선. 한 글자 주제 "K"에서 키워드 나열 52자 반환 |
| `ff7d880+46bd66acc805` | 15/15 (100%) | 프롬프트에 "단어 2~5개·30자 이내" 추가 + 코드 가드 `MAX_QUERY_CHARS` |

프롬프트를 바꾸면 결과 파일이 Prompt 버전 해시별로 남아 이전 결과와 비교할 수 있다.

## 남은 정리 (사용자 확인 필요)

- 구 리포트 생성기 대형 스캐폴드(`agent/report_builder`, `domain/`, `infrastructure/`, `workers/` 등 626개
  기능 함수와 `tests/test_feature_scaffolds.py`)는 이 방향과 무관해졌다. 삭제는 되돌리기
  어려우므로 사용자 승인 후 별도로 제거한다.
- `app/demo/`(리포트 생성기 생성 데모)도 필요 없으면 함께 정리 대상이다.
