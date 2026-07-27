"""선별 결과의 "왜 아이템이 없었는가"를 구조화된 원인으로 분류한다.

파이프라인(run_daily)은 mode("daily"/"weekly"/"evergreen") 하나로만 결과를
알려주는데, 이 값은 서로 성격이 완전히 다른 실패들을 한 덩어리로 뭉갠다. 예를 들어
"뉴스·YouTube·Reddit이 전부 타임아웃"과 "검색어가 주제를 못 맞춰 관련 문서가 없음"이
똑같이 mode="weekly"로 나온다.

이 둘을 구분하지 않으면 에이전트가 외부 장애 상황에서도 "검색어가 나빴나 보다"라며
전체 파이프라인(수집+임베딩+요약)을 반복 실행해 비용만 몇 배로 늘린다. 그래서 원인을
아래 범주로 나누고, **검색어를 바꿔서 고쳐질 수 있는 원인일 때만** 재구성을 허용한다.

원인 분류:
    success          — 당일 신규 아이템 확보 (재시도 불필요)
    provider_failure — 외부 소스·임베딩 장애 (검색어 문제 아님 → 재구성 금지)
    no_results       — 검색 결과 자체가 없거나 전부 기초 필터 탈락 (→ 재구성 유효)
    low_relevance    — 문서는 모였지만 주제와 관련도가 낮아 전멸 (→ 재구성 유효)
    duplicate_only   — 최근 보고서에 이미 실은 소식뿐 (새 소식이 없는 것 → 재구성 무의미)
    below_threshold  — 관련 문서는 있으나 점수가 발행 기준 미달 (→ 재구성해도 비슷)
    unknown          — 위 어디에도 해당하지 않음 (보수적으로 재구성 금지)
"""

from __future__ import annotations

from collections import Counter

SUCCESS = "success"
PROVIDER_FAILURE = "provider_failure"
NO_RESULTS = "no_results"
LOW_RELEVANCE = "low_relevance"
DUPLICATE_ONLY = "duplicate_only"
BELOW_THRESHOLD = "below_threshold"
UNKNOWN = "unknown"

# 검색어를 바꾸면 실제로 결과가 달라질 수 있는 원인만 재구성 대상으로 둔다.
# duplicate_only는 "오늘 새 소식이 없다"는 사실 자체라 검색어로 해결되지 않고,
# provider_failure는 외부 장애라 재시도가 비용만 키운다.
REFORMULATABLE = frozenset({NO_RESULTS, LOW_RELEVANCE})

# 사람이 읽는 원인 설명(화면·trace에 그대로 노출된다).
_DESCRIPTIONS = {
    SUCCESS: "당일 신규 아이템을 확보했습니다.",
    PROVIDER_FAILURE: "외부 소스 또는 임베딩 호출이 실패했습니다(검색어 문제 아님).",
    NO_RESULTS: "검색 결과가 없거나 모두 기초 필터에서 걸러졌습니다.",
    LOW_RELEVANCE: "문서는 모였지만 주제와의 관련도가 기준에 못 미쳤습니다.",
    DUPLICATE_ONLY: "수집된 소식이 최근 보고서에 이미 실은 것뿐입니다.",
    BELOW_THRESHOLD: "관련 문서는 있었지만 점수가 발행 기준에 못 미쳤습니다.",
    UNKNOWN: "원인을 특정하지 못했습니다.",
}


def describe(outcome: str) -> str:
    """원인 코드를 사람이 읽는 한국어 설명으로 바꾼다."""
    return _DESCRIPTIONS.get(outcome, _DESCRIPTIONS[UNKNOWN])


def should_reformulate(outcome: str) -> bool:
    """이 원인이 검색어 재구성으로 해결될 수 있는지 판단한다."""
    return outcome in REFORMULATABLE


def classify(selection: dict[str, object]) -> str:
    """run_daily 결과를 보고 실패 원인을 분류한다.

    문자열 에러 메시지를 파싱하지 않고, 파이프라인이 log에 남긴 구조화된
    필드(source_failures, embedding_failed, 단계별 잔존 건수, exclusions)만 본다.

    Args:
        selection: run_daily 반환 딕셔너리

    Returns:
        SUCCESS / PROVIDER_FAILURE / NO_RESULTS / LOW_RELEVANCE /
        DUPLICATE_ONLY / BELOW_THRESHOLD / UNKNOWN 중 하나
    """
    items = list(selection.get("items") or [])
    if selection.get("mode") == "daily" and items:
        return SUCCESS

    log = dict(selection.get("log") or {})

    # 1) 외부 장애 먼저 판정한다 — 장애로 문서를 못 받은 걸 "관련도 낮음"으로
    #    오인하면 엉뚱하게 검색어를 바꾸며 비용만 키운다.
    if log.get("embedding_failed"):
        return PROVIDER_FAILURE
    failed_sources = list(log.get("source_failures") or [])
    attempted = int(log.get("source_attempted") or 0)
    collected = int(log.get("collected") or 0)
    if failed_sources and (collected == 0 or (attempted and len(failed_sources) >= attempted)):
        return PROVIDER_FAILURE

    # 2) 수집 단계에서 아무것도 남지 않은 경우.
    if collected == 0:
        return NO_RESULTS
    if int(log.get("after_basic_filter") or 0) == 0:
        # 수집은 됐지만 오래됐거나 이미 본 URL이라 전부 탈락한 경우다. 검색어를
        # 바꾸면 다른 문서가 나올 수 있으므로 재구성 대상으로 둔다.
        return NO_RESULTS

    # 3) 유사도 필터에서 전멸 = 검색어가 주제를 제대로 못 맞춘 전형적 신호.
    if int(log.get("after_similarity_filter") or 0) == 0:
        return LOW_RELEVANCE

    # 4) 클러스터는 만들어졌는데 중복/임계값에서 걸러진 경우를 구분한다.
    stage_counts = Counter(
        str(entry.get("stage") or "") for entry in (log.get("exclusions") or [])
    )
    clusters = int(log.get("clusters") or 0)
    if clusters and stage_counts.get("dedup", 0) >= clusters:
        return DUPLICATE_ONLY
    if stage_counts.get("threshold", 0):
        return BELOW_THRESHOLD
    return UNKNOWN
