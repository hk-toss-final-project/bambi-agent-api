"""사용자별 콘텐츠 노출 이력 저장소 (YouTube 시청 + 기사 보고).

YouTube는 사용자가 실제로 영상 링크를 클릭했을 때만 "본 영상"으로 기록한다(단순
노출은 기록하지 않는다). 기사는 반대로 리포트에 실린 시점에 "보고한 기사"로
기록한다 — 같은 기사가 다음 리포트에 반복해서 실리는 것을 막는 게 목적이므로,
클릭 여부와 무관하게 노출 자체를 기억해야 하기 때문이다.

로컬 JSON 파일(data/watch_history.json, data/article_history.json)에 저장한다.
동시 접속이 많지 않은 개인용 비서 규모를 가정하며, 별도 DB 없이 파일 기반으로
관리한다.
"""

from __future__ import annotations

import json
from datetime import UTC, datetime
from pathlib import Path

_DATA_DIR = Path(__file__).resolve().parents[2] / "data"
_HISTORY_PATH = _DATA_DIR / "watch_history.json"
_ARTICLE_HISTORY_PATH = _DATA_DIR / "article_history.json"


def _normalize_keyword(keyword: str) -> str:
    """키워드를 대소문자·공백 차이 없이 조회할 수 있게 정규화한다."""
    return " ".join(keyword.strip().lower().split())


def _load_json(path: Path) -> dict[str, dict[str, dict[str, dict[str, object]]]]:
    """이력 파일을 읽는다. 파일이 없거나 깨졌으면 빈 구조를 반환한다."""
    if not path.exists():
        return {}
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return {}


def _save_json(path: Path, data: dict[str, dict[str, dict[str, dict[str, object]]]]) -> None:
    """이력 파일을 저장한다."""
    _DATA_DIR.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")


def _load() -> dict[str, dict[str, dict[str, dict[str, object]]]]:
    """시청 이력 파일을 읽는다. 파일이 없으면 빈 구조를 반환한다."""
    return _load_json(_HISTORY_PATH)


def _save(data: dict[str, dict[str, dict[str, dict[str, object]]]]) -> None:
    """시청 이력 파일을 저장한다."""
    _save_json(_HISTORY_PATH, data)


def has_watch_history(user_id: str, keyword: str) -> bool:
    """해당 사용자가 이 키워드로 이전에 본 영상이 하나라도 있는지 확인한다."""
    return bool(get_watched_video_ids(user_id, keyword))


def get_watched_video_ids(user_id: str, keyword: str) -> set[str]:
    """사용자가 해당 키워드에서 이미 본 영상 ID 집합을 반환한다."""
    data = _load()
    user_entry = data.get(user_id, {})
    keyword_entry = user_entry.get(_normalize_keyword(keyword), {})
    return set(keyword_entry.keys())


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

    data = _load()
    user_entry = data.setdefault(user_id, {})
    keyword_entry = user_entry.setdefault(_normalize_keyword(keyword), {})
    keyword_entry[video_id] = {
        "title": title,
        "url": url,
        "watched_at": datetime.now(UTC).isoformat(),
    }
    _save(data)


def get_reported_article_keys(user_id: str, keyword: str) -> set[str]:
    """사용자가 해당 키워드 리포트에서 이미 받아본 기사의 정규 URL 집합을 반환한다."""
    data = _load_json(_ARTICLE_HISTORY_PATH)
    user_entry = data.get(user_id, {})
    keyword_entry = user_entry.get(_normalize_keyword(keyword), {})
    return set(keyword_entry.keys())


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

    data = _load_json(_ARTICLE_HISTORY_PATH)
    user_entry = data.setdefault(user_id, {})
    keyword_entry = user_entry.setdefault(_normalize_keyword(keyword), {})
    keyword_entry[url_key] = {
        "title": title,
        "url": url,
        "reported_at": datetime.now(UTC).isoformat(),
    }
    _save_json(_ARTICLE_HISTORY_PATH, data)
