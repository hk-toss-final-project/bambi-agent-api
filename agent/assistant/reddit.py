"""Reddit 검색과 게시글 요약.

키워드로 관련 게시글을 검색(Reddit 공개 JSON API)하고, 각 게시글의 본문과 상위
댓글을 가져와 LLM으로 요약한다. 검색·본문 조회 등 네트워크 경계 함수를 분리해
테스트에서 대체할 수 있게 한다.
"""

from __future__ import annotations

from agent.assistant.summarize import summarize_text

_BASE_URL = "https://www.reddit.com"
# Reddit은 고유 User-Agent가 없으면 요청을 자주 차단하므로 명시한다.
_HEADERS = {"User-Agent": "bambi-keyword-assistant/0.1 (keyword digest)"}
_TIMEOUT = 12.0
# 요약 입력으로 사용할 상위 댓글 수.
_MAX_COMMENTS = 8


def search_posts(keyword: str, limit: int = 4) -> list[dict[str, object]]:
    """키워드로 Reddit 게시글을 검색해 메타데이터 목록을 반환한다.

    Args:
        keyword: 검색어
        limit: 가져올 게시글 수

    Returns:
        {id, title, url, permalink, subreddit, score, num_comments, selftext} 리스트
    """
    import httpx

    response = httpx.get(
        f"{_BASE_URL}/search.json",
        params={"q": keyword, "limit": limit, "sort": "relevance"},
        headers=_HEADERS,
        timeout=_TIMEOUT,
    )
    response.raise_for_status()
    data = response.json()

    posts: list[dict[str, object]] = []
    for child in data.get("data", {}).get("children", []):
        item = child.get("data", {})
        permalink = item.get("permalink", "")
        posts.append(
            {
                "id": item.get("id"),
                "title": item.get("title"),
                "url": f"{_BASE_URL}{permalink}" if permalink else item.get("url"),
                "permalink": permalink,
                "subreddit": item.get("subreddit"),
                "score": item.get("score"),
                "num_comments": item.get("num_comments"),
                "selftext": item.get("selftext", ""),
            }
        )
    return posts


def fetch_comments(permalink: str, max_comments: int = _MAX_COMMENTS) -> list[str]:
    """게시글의 상위 댓글 본문 목록을 가져온다. 실패하면 빈 리스트를 반환한다."""
    import httpx

    try:
        response = httpx.get(
            f"{_BASE_URL}{permalink}.json",
            params={"limit": max_comments},
            headers=_HEADERS,
            timeout=_TIMEOUT,
        )
        response.raise_for_status()
        listing = response.json()
    except Exception:
        return []

    # listing[0]은 게시글, listing[1]은 댓글 목록이다.
    if len(listing) < 2:
        return []
    comments: list[str] = []
    for child in listing[1].get("data", {}).get("children", []):
        body = child.get("data", {}).get("body")
        if body:
            comments.append(body)
        if len(comments) >= max_comments:
            break
    return comments


def summarize_post(post: dict[str, object], model: str = "gpt-4.1-mini") -> dict[str, object]:
    """게시글 하나의 본문·댓글을 요약해 결과 딕셔너리를 만든다.

    본문(selftext)과 상위 댓글을 합쳐 요약한다. 둘 다 없으면 안내 문구를 넣는다.
    """
    parts: list[str] = []
    selftext = str(post.get("selftext") or "").strip()
    if selftext:
        parts.append(selftext)

    comments = fetch_comments(str(post.get("permalink") or ""))
    if comments:
        parts.append("상위 댓글:\n" + "\n".join(comments))

    content = "\n\n".join(parts).strip()
    if content:
        summary = summarize_text(
            content,
            instruction=f"다음 Reddit 게시글 '{post.get('title')}'의 본문과 댓글을 요약해줘.",
            model=model,
        )
        note = None
    else:
        summary = None
        note = "본문과 댓글이 없어 요약할 수 없습니다."

    return {
        "title": post.get("title"),
        "url": post.get("url"),
        "subreddit": post.get("subreddit"),
        "score": post.get("score"),
        "num_comments": post.get("num_comments"),
        "summary": summary,
        "note": note,
    }


def reddit_digest(keyword: str, limit: int = 4, model: str = "gpt-4.1-mini") -> list[dict[str, object]]:
    """키워드로 게시글을 검색하고 각 게시글의 요약 목록을 반환한다."""
    posts = search_posts(keyword, limit=limit)
    return [summarize_post(post, model=model) for post in posts]
