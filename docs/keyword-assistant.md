# 키워드 비서 AI — 개발 명세

> 이 문서는 프로젝트의 새 방향인 "키워드 → 관련 URL/영상 수집·요약 비서"의 명세입니다.
> 기존 `agent-api-feature-spec.md` / `agent-api-mvp-scope.md`의 대형 밤비 에이전트
> 명세는 이 방향으로 재편 중이며, 관련 스캐폴드는 단계적으로 정리합니다.

## 목표

키워드를 입력하면 다음을 한 화면에서 제공한다.

1. **YouTube 요약**: 키워드로 관련 영상을 검색하고, 각 영상의 자막을 LLM으로 요약한다.
2. **최신 기사 URL**: RSS(Google News 검색 피드)로 최신 기사를 모으고, Jina Reader로
   본문을 정제한 뒤, URL·제목 기준으로 중복을 제거해 제공한다.

## 구성

| 영역 | 파일 | 역할 |
|---|---|---|
| YouTube | [agent/assistant/youtube.py](../agent/assistant/youtube.py) | 검색(youtube-search-python), 자막(youtube-transcript-api), 자막 요약 |
| RSS·Jina | [agent/assistant/feeds.py](../agent/assistant/feeds.py) | Google News RSS 조회, Jina Reader 정제, 최신순 정렬 + 중복 제거 |
| 요약 | [agent/assistant/summarize.py](../agent/assistant/summarize.py) | ChatOpenAI 기반 한국어 요약 헬퍼 |
| 오케스트레이션 | [agent/assistant/service.py](../agent/assistant/service.py) | 키워드 → {youtube, articles, errors} 결합 (소스별 실패 격리) |
| 웹 | [app/assistant/web.py](../app/assistant/web.py) | `/` 키워드 폼, `/search` 결과 페이지 |

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

키워드 비서 웹 UI는 **Agent API 서버와 별도 포트로 실행되는 독립 앱**이다. API 서버
(`app.main:app`)는 순수 API만 제공하고, 사람이 접속하는 비서 화면은 `app.assistant.main:app`이
담당한다.

```bash
# 방법 1) 둘을 한 번에 실행 (API 8000 + 비서 UI 8100)
uv run python scripts/run_all.py

# 방법 2) 각각 따로 실행
uv run uvicorn app.main:app --port 8000              # Agent API
uv run uvicorn app.assistant.main:app --port 8100    # 키워드 비서 UI
```

- Agent API      : <http://127.0.0.1:8000>  (docs: `/redoc`)
- 키워드 비서 UI : <http://127.0.0.1:8100>  ← 브라우저로 접속해 키워드 입력

## 테스트

- [tests/agent/assistant/](../tests/agent/assistant/) — 검색/자막/요약/피드/중복 제거/오케스트레이션을
  네트워크·LLM 호출 없이 mock으로 검증한다. `uv run pytest`는 무료·결정적으로 통과한다.

## 남은 정리 (사용자 확인 필요)

- 구 밤비 대형 스캐폴드(`agent/bambi`, `domain/`, `infrastructure/`, `workers/` 등 626개
  기능 함수와 `tests/test_feature_scaffolds.py`)는 이 방향과 무관해졌다. 삭제는 되돌리기
  어려우므로 사용자 승인 후 별도로 제거한다.
- `app/demo/`(밤비 생성 데모)도 필요 없으면 함께 정리 대상이다.
