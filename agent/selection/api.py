"""선별 기능 영역의 공개 facade.

브리핑(agent/assistant)과 리포트(agent/report_builder)가 **같은 선별 기준**을 쓰도록
공용화한 계층이다. 구현 모듈(features/)의 함수를 안정적인 import 경로로 다시
노출하며, 외부 계층은 features/를 직접 참조하지 않는다(AGENTS.md 규칙 9).

이 영역은 전체 명세 1~43절의 기능 ID 체계에 속하지 않는 내부 공용 라이브러리라
기능-ID 형식 함수를 두지 않는다.

중복 이력은 `DedupHistory` Protocol로 주입받는다 — 넘기지 않으면 읽지도 쓰지도
않으므로, 이력을 건드리면 안 되는 소비자(리포트 생성)가 실수로 기록할 수 없다.
"""

from .features import config, outcomes
from .features.clustering import greedy_clusters
from .features.dedup import (
    STATUS_DUPLICATE,
    STATUS_NEW,
    STATUS_UPDATE,
    DedupHistory,
    check_duplicate,
    load_recent_report_items,
    record_report_items,
)
from .features.embeddings import cosine_similarity, embed_texts
from .features.outcomes import (
    BELOW_THRESHOLD,
    DUPLICATE_ONLY,
    LOW_RELEVANCE,
    NO_RESULTS,
    PROVIDER_FAILURE,
    REFORMULATABLE,
    SUCCESS,
    UNKNOWN,
    classify,
    describe,
    should_reformulate,
)
from .features.scoring import (
    classify_content_type,
    cluster_boost,
    final_score,
    freshness_score,
    score_document,
    source_weight,
)

__all__ = [
    "BELOW_THRESHOLD",
    "DUPLICATE_ONLY",
    "DedupHistory",
    "LOW_RELEVANCE",
    "NO_RESULTS",
    "PROVIDER_FAILURE",
    "REFORMULATABLE",
    "STATUS_DUPLICATE",
    "STATUS_NEW",
    "STATUS_UPDATE",
    "SUCCESS",
    "UNKNOWN",
    "check_duplicate",
    "classify",
    "classify_content_type",
    "cluster_boost",
    "config",
    "cosine_similarity",
    "describe",
    "embed_texts",
    "final_score",
    "freshness_score",
    "greedy_clusters",
    "outcomes",
    "load_recent_report_items",
    "record_report_items",
    "score_document",
    "should_reformulate",
    "source_weight",
]
