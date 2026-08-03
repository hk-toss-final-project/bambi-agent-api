<!-- 테스트용 비서 UI 제거 시 무엇을 지우고 무엇을 남겨야 하는지 정리한 문서. -->

# 비서 UI(`/assistant`) 제거 안내

> 상태: **제거 예정 (시점 미정)** · 작성일 2026-07-31
> 결정: `/assistant` 페이지는 테스트용이므로 나중에 없앤다.

## 왜 이 문서가 필요한가

**이름이 같은 두 패키지가 있고, 하나만 지워야 한다.**

```
app/assistant/     ← 테스트용 웹 페이지.        제거 대상
agent/assistant/   ← 수집 파이프라인.          절대 지우면 안 됨
```

`agent/assistant/`는 리포트 생성의 핵심 부품이다. 폴더 이름만 보고 함께
지우면 리포트 생성이 통째로 멈춘다.

## 남겨야 하는 것 — `agent/assistant/`

리포트 생성이 세 군데에서 쓴다.

| 사용처 | 가져다 쓰는 것 | 역할 |
|---|---|---|
| [live_sources.py:23](../agent/report_builder/features/live_sources.py:23) | `assist_daily_agent` | 조사원의 `collect_live` 도구가 실행하는 수집 엔진 |
| [pool_context.py:32](../agent/report_builder/features/pool_context.py:32) | `clean_article_body` | Jina로 읽은 기사에서 메뉴·푸터 제거 |
| [graph.py:55](../agent/graph.py:55) | `resolve_topic_intent` | 토픽이 뉴스인지 개념인지 판정(신선도 하한 결정) |

특히 `assist_daily_agent`는 **조사원이 인터넷을 뒤질 때 부르는 유일한 경로**다.
이것이 없으면 창고에 없는 주제는 자료를 전혀 못 모은다.

## 지워도 되는 것 — `app/assistant/`

`app/assistant/web.py` 한 파일과 그 라우터 등록뿐이다.

## 제거 절차

### 1. 지금 당장은 끄기만 해도 된다

[app/main.py:106](../app/main.py:106)에 이미 스위치가 있다.

```python
if settings.enable_assistant_ui:
    from app.assistant.web import assistant_router
```

`ENABLE_ASSISTANT_UI=false`로 두면 운영에 노출되지 않는다. **코드를 지우기
전에 이 값으로 먼저 꺼 두고 문제가 없는지 확인하는 것을 권한다.**

### 2. 실제로 지울 때

1. `app/assistant/` 디렉터리 삭제
2. `app/main.py`의 라우터 등록 블록과 `enable_assistant_ui` 설정 제거
3. `.env.example`에서 `ENABLE_ASSISTANT_UI` 제거
4. 관련 테스트 정리
5. `uv run pytest` 통과 확인

### 3. `/dev/graphs` 등록은 지우지 말고 고친다

[graph_diagrams.py:14](../app/services/graph_diagrams.py:14)가 키워드 비서
그래프를 독립 항목으로 보여준다.

```python
from agent.assistant.api import build_assistant_graph
```

**이 그래프는 UI를 지운 뒤에도 계속 돈다** — 조사원의 `collect_live` 안에서
실행되기 때문이다. 목록에서 빼면 실제로 동작하는 코드가 그림에서 사라진다.

따라서 항목은 유지하되 **설명을 고친다.** 지금은 독립 실행처럼 읽히지만,
실제로는 조사원의 도구가 실행하는 하위 그래프다.

> AGENTS.md 규칙 10은 `agent/`의 StateGraph 수와 레지스트리 항목 수를
> 대조하는 가드 테스트를 두고 있다. 등록을 빼면 그 테스트가 실패한다.

## 참고 — 두 패키지의 관계

```
리포트 생성 그래프
  └─ research 노드 (조사원)
       ├─ search_pool    → DB
       └─ collect_live   → agent/assistant/ 파이프라인 실행
                             plan → select → reformulate ⇄ select

app/assistant/  ← 같은 파이프라인을 웹에서 직접 실행해 보는 테스트 페이지
```

UI는 파이프라인을 **직접 호출하는 또 하나의 진입점**일 뿐이며, 파이프라인
자체는 리포트 생성이 계속 사용한다.
