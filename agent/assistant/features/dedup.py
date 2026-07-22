"""일간 보고서 중복 방지 (보고서 로직과 독립).

최근 DEDUP_LOOKBACK_DAYS일간 보고서에 실린 아이템의 임베딩을 보관하고, 새 후보와의
코사인 유사도로 "이미 다룬 소식"인지 판정한다. 저장 위치는 [storage.py](storage.py)가
정한다(PostgreSQL 우선, 없으면 로컬 JSON).

판정 규칙:
- 유사도 < DUP_THRESHOLD                         → "new" (신규)
- 유사도 ≥ DUP_STRICT_THRESHOLD                  → "duplicate" (사실상 같은 문서)
- DUP_THRESHOLD ≤ 유사도 < DUP_STRICT_THRESHOLD:
    후보 발행일이 기존 보고 시각보다 나중이면      → "update" (후속 업데이트, 포함 가능)
    아니면                                        → "duplicate"

멱등성: 같은 날 재실행 시 "오늘 이미 기록한 아이템"은 중복 검사에서 제외해
동일한 보고서가 다시 만들어질 수 있게 하고, 기록은 URL 키로 덮어써 이력이
불어나지 않게 한다.
"""

from __future__ import annotations

from datetime import UTC, datetime

from agent.assistant.features import config, storage
from agent.assistant.features.embeddings import cosine_similarity

STATUS_NEW = "new"
STATUS_DUPLICATE = "duplicate"
STATUS_UPDATE = "update"


def _normalize_keyword(keyword: str) -> str:
    """키워드를 대소문자·공백 차이 없이 조회할 수 있게 정규화한다."""
    return storage.normalize_keyword(keyword)


def _parse_reported_at(entry: dict[str, object]) -> datetime | None:
    """이력 항목의 reported_at을 datetime으로 파싱한다. 실패 시 None."""
    raw = str(entry.get("reported_at") or "")
    if not raw:
        return None
    try:
        parsed = datetime.fromisoformat(raw)
    except ValueError:
        return None
    return parsed if parsed.tzinfo else parsed.replace(tzinfo=UTC)


def load_recent_report_items(
    user_id: str,
    keyword: str,
    *,
    now: datetime | None = None,
    lookback_days: int | None = None,
    exclude_today: bool = True,
) -> list[dict[str, object]]:
    """중복 검사에 쓸 최근 보고 아이템 목록을 반환한다.

    lookback_days보다 오래된 항목은 제외한다. exclude_today=True면 오늘(now와
    같은 날짜)에 기록된 항목도 제외한다 — 같은 날 재실행 시 방금 만든 보고서와
    비교해 전부 중복 처리되는 것을 막기 위한 멱등성 장치다.
    """
    reference = now or datetime.now(UTC)
    if not user_id:
        return []
    cutoff = storage.lookback_cutoff(reference, lookback_days)
    exclude_date = reference.date() if exclude_today else None
    return storage.get_store().load_recent_report_items(
        user_id, keyword, cutoff=cutoff, exclude_date=exclude_date
    )


def check_duplicate(
    candidate_embedding: list[float],
    candidate_published: datetime | None,
    history_items: list[dict[str, object]],
    *,
    dup_threshold: float | None = None,
    strict_threshold: float | None = None,
) -> tuple[str, dict[str, object] | None, float]:
    """후보 임베딩을 최근 보고 이력과 비교해 중복 여부를 판정한다.

    Args:
        candidate_embedding: 후보 문서(클러스터 대표)의 임베딩
        candidate_published: 후보 발행일 (모르면 None)
        history_items: load_recent_report_items 결과

    Returns:
        (판정, 가장 유사한 이력 항목 또는 None, 최고 유사도)
        판정: STATUS_NEW | STATUS_DUPLICATE | STATUS_UPDATE
    """
    dup_cut = config.DUP_THRESHOLD if dup_threshold is None else dup_threshold
    strict_cut = config.DUP_STRICT_THRESHOLD if strict_threshold is None else strict_threshold

    best_item: dict[str, object] | None = None
    best_sim = 0.0
    for item in history_items:
        embedding = item.get("embedding")
        if not isinstance(embedding, list):
            continue
        sim = cosine_similarity(candidate_embedding, embedding)
        if sim > best_sim:
            best_sim = sim
            best_item = item

    if best_item is None or best_sim < dup_cut:
        return STATUS_NEW, best_item, best_sim
    if best_sim >= strict_cut:
        return STATUS_DUPLICATE, best_item, best_sim

    reported_at = best_item.get("reported_at_dt")
    if (
        candidate_published is not None
        and isinstance(reported_at, datetime)
        and candidate_published > reported_at
    ):
        return STATUS_UPDATE, best_item, best_sim
    return STATUS_DUPLICATE, best_item, best_sim


def record_report_items(
    user_id: str,
    keyword: str,
    items: list[dict[str, object]],
    *,
    now: datetime | None = None,
) -> None:
    """보고서에 실은 아이템의 임베딩을 이력에 기록하고 오래된 항목을 정리한다.

    items의 각 항목은 {url_key, title, embedding}을 가져야 한다. 같은 url_key는
    덮어쓰므로 같은 날 재실행해도 이력이 중복으로 쌓이지 않는다.
    """
    if not user_id or not items:
        return
    reference = now or datetime.now(UTC)
    # 오래된 항목 정리는 조회가 아니라 기록 시점에 한 번씩 한다.
    cutoff = storage.lookback_cutoff(reference)
    storage.get_store().record_report_items(
        user_id, keyword, items, reference=reference, cutoff=cutoff
    )
