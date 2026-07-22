"""사용자별 콘텐츠 노출 이력 (YouTube 시청 + 기사 보고 + 수집 이력).

YouTube는 사용자가 실제로 영상 링크를 클릭했을 때만 "본 영상"으로 기록한다(단순
노출은 기록하지 않는다). 기사는 반대로 리포트에 실린 시점에 "보고한 기사"로
기록한다 — 같은 기사가 다음 리포트에 반복해서 실리는 것을 막는 게 목적이므로,
클릭 여부와 무관하게 노출 자체를 기억해야 하기 때문이다.

수집 이력(collect_history)은 같은 사용자가 이미 수집한 URL의 first_seen(최초
발견 시각)을 기억한다. 같은 URL을 다시 만나도 first_seen을 덮어쓰지 않아
(1) 재수집으로 새 문서처럼 처리되는 것을 막고, (2) 발행일 추출이 전부 실패한
문서의 발행일 대용으로 쓴다. 스코어(final_score)도 함께 기록해 주간 트렌드
폴백에서 "최근 7일 최고 점수 이슈"를 고를 수 있게 한다.

실제 저장 위치는 [storage.py](storage.py)가 정한다 — PostgreSQL이 있으면 DB,
없으면 로컬 JSON 파일이다. 이 모듈은 공개 함수 시그니처만 유지하는 얇은 층이라
호출부는 저장 위치를 알 필요가 없다.
"""

from __future__ import annotations

from datetime import UTC, datetime

from agent.assistant.features import storage


def _normalize_keyword(keyword: str) -> str:
    """키워드를 대소문자·공백 차이 없이 조회할 수 있게 정규화한다."""
    return storage.normalize_keyword(keyword)


def has_watch_history(user_id: str, keyword: str) -> bool:
    """해당 사용자가 이 키워드로 이전에 본 영상이 하나라도 있는지 확인한다."""
    return bool(get_watched_video_ids(user_id, keyword))


def get_watched_video_ids(user_id: str, keyword: str) -> set[str]:
    """사용자가 해당 키워드에서 이미 본 영상 ID 집합을 반환한다."""
    if not user_id:
        return set()
    return storage.get_store().get_watched_video_ids(user_id, keyword)


def record_watch(user_id: str, keyword: str, video_id: str, title: str, url: str) -> None:
    """사용자가 실제로 클릭한 영상을 시청 이력에 기록한다.

    Args:
        user_id: 사용자 식별자
        keyword: 이 영상을 발견한 검색 키워드
        video_id: YouTube 영상 ID
        title: 영상 제목 (기록용)
        url: 영상 URL (기록용)
    """
    if not user_id or not video_id:
        return
    storage.get_store().record_watch(user_id, keyword, video_id, title, url)


def get_reported_article_keys(user_id: str, keyword: str) -> set[str]:
    """사용자가 해당 키워드 리포트에서 이미 받아본 기사의 정규 URL 집합을 반환한다."""
    if not user_id:
        return set()
    return storage.get_store().get_reported_article_keys(user_id, keyword)


def record_reported_article(user_id: str, keyword: str, url_key: str, title: str, url: str) -> None:
    """리포트에 실린 기사를 보고 이력에 기록한다.

    Args:
        user_id: 사용자 식별자
        keyword: 이 기사를 발견한 검색 키워드
        url_key: 중복 판별용 정규 URL (feeds.canonical_url 결과)
        title: 기사 제목 (기록용)
        url: 기사 원본 URL (기록용)
    """
    if not user_id or not url_key:
        return
    storage.get_store().record_reported_article(user_id, keyword, url_key, title, url)


def get_collected_entries(user_id: str, keyword: str) -> dict[str, dict[str, object]]:
    """사용자·키워드의 수집 이력을 반환한다. {url_key: {first_seen, title, url, score}}"""
    if not user_id:
        return {}
    return storage.get_store().get_collected_entries(user_id, keyword)


def has_collect_history(user_id: str, keyword: str) -> bool:
    """이 사용자·키워드로 수집한 이력이 하나라도 있는지 확인한다 (콜드 스타트 판정)."""
    return bool(get_collected_entries(user_id, keyword))


def record_collected(
    user_id: str,
    keyword: str,
    url_key: str,
    title: str,
    url: str,
    *,
    first_seen: datetime | None = None,
    score: float | None = None,
) -> datetime:
    """수집한 문서를 이력에 기록하고 first_seen을 반환한다.

    같은 URL이 이미 기록돼 있으면 first_seen은 덮어쓰지 않고 기존 값을 유지한다
    (같은 날 재실행 멱등성). score는 최신 계산값으로 갱신한다.

    Args:
        user_id: 사용자 식별자
        keyword: 이 문서를 발견한 검색 키워드
        url_key: 중복 판별용 정규 URL (feeds.canonical_url 결과)
        title: 문서 제목 (기록용)
        url: 문서 원본 URL (기록용)
        first_seen: 최초 발견 시각. 생략하면 현재 시각.
        score: 이번 실행에서 계산한 final_score (주간 트렌드 폴백용)

    Returns:
        이 URL의 확정된 first_seen (기존 기록이 있으면 그 값)
    """
    now = first_seen or datetime.now(UTC)
    if not user_id or not url_key:
        return now
    return storage.get_store().record_collected(
        user_id, keyword, url_key, title, url, first_seen=now, score=score
    )


def get_first_seen(user_id: str, keyword: str, url_key: str) -> datetime | None:
    """해당 URL의 first_seen(최초 발견 시각)을 반환한다. 기록이 없으면 None."""
    entry = get_collected_entries(user_id, keyword).get(url_key)
    if not entry or not entry.get("first_seen"):
        return None
    try:
        return datetime.fromisoformat(str(entry["first_seen"]))
    except ValueError:
        return None
