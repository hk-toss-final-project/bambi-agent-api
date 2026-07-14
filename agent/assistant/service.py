"""키워드 비서 오케스트레이터.

키워드 하나를 받아 YouTube 자막 요약과 최신 기사 URL 수집을 함께 수행하고,
웹/엔드포인트가 바로 렌더링할 수 있는 결과 딕셔너리로 묶는다.

각 소스는 독립적으로 실패할 수 있으므로, 한쪽이 실패해도 다른 결과는 그대로
반환하고 실패 사유를 errors에 담는다.
"""

from __future__ import annotations

from agent.assistant.feeds import latest_articles
from agent.assistant.reddit import reddit_digest
from agent.assistant.youtube import youtube_digest


def assist(
    keyword: str,
    *,
    youtube_limit: int = 4,
    reddit_limit: int = 4,
    article_limit: int = 6,
    model: str = "gpt-4.1-mini",
) -> dict[str, object]:
    """키워드로 YouTube·Reddit 요약과 최신 기사 URL을 모아 반환한다.

    Args:
        keyword: 사용자 검색 키워드
        youtube_limit: 검색·요약할 YouTube 영상 수
        reddit_limit: 검색·요약할 Reddit 게시글 수
        article_limit: 반환할 최신 기사 수
        model: 요약에 사용할 OpenAI 모델

    Returns:
        {keyword, youtube, reddit, articles, errors} 딕셔너리
    """
    normalized = keyword.strip()
    if not normalized:
        raise ValueError("키워드가 비어 있습니다.")

    errors: list[str] = []

    try:
        youtube = youtube_digest(normalized, limit=youtube_limit, model=model)
    except Exception as error:
        youtube = []
        errors.append(f"YouTube 처리 실패: {type(error).__name__}: {error}")

    try:
        reddit = reddit_digest(normalized, limit=reddit_limit, model=model)
    except Exception as error:
        reddit = []
        errors.append(f"Reddit 처리 실패: {type(error).__name__}: {error}")

    try:
        articles = latest_articles(normalized, limit=article_limit)
    except Exception as error:
        articles = []
        errors.append(f"기사 수집 실패: {type(error).__name__}: {error}")

    return {
        "keyword": normalized,
        "youtube": youtube,
        "reddit": reddit,
        "articles": articles,
        "errors": errors,
    }
