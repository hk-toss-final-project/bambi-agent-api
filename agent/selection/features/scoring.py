"""문서 스코어링 (보고서 로직과 독립).

final_score = similarity × freshness × source_weight × cluster_boost

- similarity: 사용자 토픽 임베딩과의 코사인 유사도 (0~1)
- freshness: exp(-λ × 경과일수). λ는 콘텐츠 타입(뉴스/에버그린)별 설정값.
  콜드 스타트이거나 발행일 미상이면 중립값(COLD_START_FRESHNESS)으로 고정.
- source_weight: config의 소스 신뢰도 테이블 (도메인 기준)
- cluster_boost: 1 + 0.1 × (클러스터 크기 - 1), 상한 CLUSTER_BOOST_CAP.
  하드 필터가 아니라 가중치로만 쓴다(소스 1개짜리 공식 릴리스도 선정 가능).

나중에 wiki 저장소가 붙어도 재사용할 수 있도록 순수 함수로만 구성하고,
보고서 생성 로직을 import하지 않는다.
"""

from __future__ import annotations

import math
import re
from datetime import UTC, datetime
from urllib.parse import urlsplit

from agent.selection.features import config

# 제목에 이 패턴이 보이면 에버그린(개념/튜토리얼) 콘텐츠로 분류한다.
# 소스 기반 1차 분류를 보완하는 가벼운 휴리스틱이며, 필요해지면 LLM 분류로 교체한다.
_EVERGREEN_TITLE_PATTERN = re.compile(
    r"(튜토리얼|강의|강좌|입문|기초|개념|정리|가이드|사용법|배우기"
    r"|tutorial|guide|introduction|how\s+to|explained|basics|course)",
    re.IGNORECASE,
)


def classify_content_type(doc: dict[str, object]) -> str:
    """문서를 "news" 또는 "evergreen"으로 분류한다.

    제목의 개념/튜토리얼 키워드로 판단하는 휴리스틱이다. 해당 없으면 뉴스로 본다.
    """
    title = str(doc.get("title") or "")
    if _EVERGREEN_TITLE_PATTERN.search(title):
        return "evergreen"
    return "news"


def freshness_score(
    published: datetime | None,
    content_type: str,
    *,
    now: datetime | None = None,
    cold_start: bool = False,
) -> float:
    """신선도 점수 exp(-λ × 경과일수)를 계산한다.

    콜드 스타트(첫 실행)이거나 발행일을 알 수 없으면 중립값을 반환한다.

    Args:
        published: 발행일 (없으면 None)
        content_type: "news" 또는 "evergreen"
        now: 기준 시각 (테스트용, 생략 시 현재)
        cold_start: 첫 실행 여부. True면 발행일과 무관하게 중립값 고정.
    """
    if cold_start or published is None:
        return config.COLD_START_FRESHNESS

    reference = now or datetime.now(UTC)
    age_days = max((reference - published).total_seconds() / 86400.0, 0.0)
    decay = config.LAMBDA_EVERGREEN if content_type == "evergreen" else config.LAMBDA_NEWS
    return math.exp(-decay * age_days)


def source_weight(url: str) -> float:
    """URL의 도메인으로 소스 신뢰도 가중치를 찾는다. 미등록 소스는 기본값."""
    domain = urlsplit(str(url or "").strip()).netloc
    return config.source_weight_for_domain(domain)


def cluster_boost(cluster_size: int) -> float:
    """클러스터 크기에 따른 부스트 1 + 0.1 × (크기 - 1)를 상한까지 계산한다."""
    if cluster_size < 1:
        return 1.0
    return min(1.0 + 0.1 * (cluster_size - 1), config.CLUSTER_BOOST_CAP)


def final_score(
    similarity: float,
    freshness: float,
    source_w: float,
    boost: float = 1.0,
) -> float:
    """final_score = similarity × freshness × source_weight × cluster_boost."""
    return similarity * freshness * source_w * boost


def score_document(
    doc: dict[str, object],
    similarity: float,
    *,
    boost: float = 1.0,
    now: datetime | None = None,
    cold_start: bool = False,
) -> dict[str, float | str]:
    """문서 하나의 점수 구성 요소와 final_score를 계산해 딕셔너리로 반환한다.

    doc은 {title, url, published(datetime|None)} 키를 가진 문서 딕셔너리다.
    source_url(원본 발행처 URL)이 있으면 소스 가중치는 그쪽을 우선한다 — 뉴스
    문서의 url은 Google News 리다이렉트 주소라 발행처를 판별할 수 없기 때문이다.

    Returns:
        {content_type, similarity, freshness, source_weight, cluster_boost, final_score}
    """
    content_type = classify_content_type(doc)
    published = doc.get("published")
    freshness = freshness_score(
        published if isinstance(published, datetime) else None,
        content_type,
        now=now,
        cold_start=cold_start,
    )
    weight = source_weight(str(doc.get("source_url") or doc.get("url") or ""))
    return {
        "content_type": content_type,
        "similarity": similarity,
        "freshness": freshness,
        "source_weight": weight,
        "cluster_boost": boost,
        "final_score": final_score(similarity, freshness, weight, boost),
    }
