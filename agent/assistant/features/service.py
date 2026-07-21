"""키워드 비서 오케스트레이터.

키워드 하나를 받아 YouTube 자막 요약과 최신 기사 URL 수집을 함께 수행하고,
웹/엔드포인트가 바로 렌더링할 수 있는 결과 딕셔너리로 묶는다.

각 소스는 독립적으로 실패할 수 있으므로, 한쪽이 실패해도 다른 결과는 그대로
반환하고 실패 사유를 errors에 담는다.

`assist`는 기존 웹 UI가 쓰는 소스별 나열 결과이고, `assist_daily`는 명세의
선별 파이프라인(수집→임베딩→클러스터링→스코어링→중복 제거→임계값+워터폴)을
거친 일간 보고서 결과다. `assist_daily_agent`는 그 파이프라인을 도구로 감싼
리서치 에이전트(graph)를 실행해, 결과가 빈약하면 검색어를 재구성해 다시
시도하는 판단까지 포함한 결과다.
"""

from __future__ import annotations

from agent.assistant.features import graph, history, pipeline
from agent.assistant.features.feeds import canonical_url, latest_articles
from agent.assistant.features.reddit import reddit_digest
from agent.assistant.features.report import generate_daily_report
from agent.assistant.features.youtube import youtube_digest_for_user


def assist(
    keyword: str,
    *,
    user_id: str,
    youtube_limit: int = 4,
    reddit_limit: int = 4,
    article_limit: int = 6,
    model: str = "gpt-4.1-mini",
) -> dict[str, object]:
    """키워드로 YouTube·Reddit 요약과 최신 기사 URL을 모아 반환한다.

    YouTube는 최근(48시간 이내) 영상 중 사용자가 아직 보지 않은 영상만 남긴다.
    첫 조회 여부와 무관하게 항상 최신성 기준을 적용한다.

    기사는 보고 이력을 반영해 개인화한다: 최근 발행된 기사 중 이번 리포트에
    처음 싣는 기사만 반환하고, 실은 기사는 이력에 기록해 다음 리포트에서
    반복되지 않게 한다. 새 기사가 없으면 빈 목록을 반환한다(새 소식 없음).

    Args:
        keyword: 사용자 검색 키워드
        user_id: 시청 이력을 구분할 사용자 식별자
        youtube_limit: 검색·요약할 YouTube 영상 수
        reddit_limit: 검색·요약할 Reddit 게시글 수
        article_limit: 반환할 최신 기사 수
        model: 요약에 사용할 OpenAI 모델

    Returns:
        {keyword, user_id, youtube, reddit, articles, errors} 딕셔너리
    """
    normalized = keyword.strip()
    if not normalized:
        raise ValueError("키워드가 비어 있습니다.")
    normalized_user_id = user_id.strip()
    if not normalized_user_id:
        raise ValueError("사용자 식별자가 비어 있습니다.")

    errors: list[str] = []

    try:
        youtube = youtube_digest_for_user(normalized, normalized_user_id, limit=youtube_limit, model=model)
    except Exception as error:
        youtube = []
        errors.append(f"YouTube 처리 실패: {type(error).__name__}: {error}")

    try:
        reddit = reddit_digest(normalized, limit=reddit_limit, model=model)
    except Exception as error:
        reddit = []
        errors.append(f"Reddit 처리 실패: {type(error).__name__}: {error}")

    try:
        # 이미 리포트에 실었던 기사는 제외하고, 새로 실은 기사는 이력에 기록한다.
        already_reported = history.get_reported_article_keys(normalized_user_id, normalized)
        articles = latest_articles(normalized, limit=article_limit, exclude_urls=already_reported)
        for article in articles:
            history.record_reported_article(
                normalized_user_id,
                normalized,
                canonical_url(str(article.get("url") or "")),
                str(article.get("title") or ""),
                str(article.get("url") or ""),
            )
    except Exception as error:
        articles = []
        errors.append(f"기사 수집 실패: {type(error).__name__}: {error}")

    return {
        "keyword": normalized,
        "user_id": normalized_user_id,
        "youtube": youtube,
        "reddit": reddit,
        "articles": articles,
        "errors": errors,
    }


def assist_daily(
    keyword: str,
    *,
    user_id: str,
    model: str = "gpt-4.1-mini",
) -> dict[str, object]:
    """선별 파이프라인을 실행하고 일간 보고서까지 생성해 반환한다.

    수집 소스는 기존 그대로 쓰되, 명세의 선별 로직(최근 N일 수집 창, 날짜 추출,
    임베딩 유사도 필터, 클러스터링 통합 요약, 스코어링, 최근 7일 중복 제거,
    임계값 + 워터폴 폴백)을 적용한다.

    Args:
        keyword: 사용자 관심 토픽
        user_id: 사용자 식별자
        model: 통합 요약·보고서 생성에 쓸 OpenAI 모델

    Returns:
        {keyword, user_id, mode, cold_start, items, report_markdown, log, errors}
        mode는 "daily"(당일 신규) | "weekly"(주간 트렌드 폴백) | "evergreen"(개념 정리 폴백)
    """
    result = pipeline.run_daily(keyword, user_id, model=model)

    try:
        report_markdown = generate_daily_report(result, model=model)
    except Exception as error:
        report_markdown = ""
        errors = result.setdefault("errors", [])
        assert isinstance(errors, list)
        errors.append(f"보고서 생성 실패: {type(error).__name__}: {error}")

    return {**result, "report_markdown": report_markdown}


def assist_daily_agent(
    keyword: str,
    *,
    user_id: str,
    model: str = "gpt-4.1-mini",
) -> dict[str, object]:
    """리서치 에이전트를 실행해 일간 보고서를 생성한다.

    `assist_daily`와 결과 형태(mode·items·report_markdown·log·errors)는 같되,
    수집 결과가 빈약할 때 에이전트가 검색어를 재구성해 다시 시도한다. 어떤 판단을
    했는지는 agent_trace, 시도한 검색어는 attempts로 함께 반환한다.

    Args:
        keyword: 사용자 관심 토픽
        user_id: 사용자 식별자
        model: 재구성·요약·보고서 생성에 쓸 OpenAI 모델

    Returns:
        assist_daily 결과 + {agent_trace: [str], attempts: [str]}
    """
    return graph.run_agent(keyword, user_id, model=model)
