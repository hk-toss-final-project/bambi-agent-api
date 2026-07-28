"""Global 풀 검색 결과를 평가해 실시간 수집을 생략할지 판정한다.

리포트 생성은 개인 Wiki·Global 풀을 검색(prag_003)해 놓고도 **항상** 실시간 수집을
수행한다. 풀에 쓸 만한 자료가 이미 있어도 뉴스·YouTube·Reddit을 다시 훑기 때문에
실행 시간 대부분이 여기서 나온다(2026-07-28 실측: 리포트 1건 41.5초).

이 모듈은 "풀 결과가 충분한가"를 판정해 그 수집을 건너뛸 수 있게 한다. 판정은
두 단계다.

1. **점수 컷오프** — 풀 검색은 하한 없이 Scope별 상위 N건을 그대로 반환하므로
   무관한 문서가 섞인다(실측: 'Anthropic' 검색에 "암호화폐 버리고 AI로?" score
   0.061). 절대 하한이 아니라 이번 검색 최고점 대비 상대 비율을 쓴다 — 점수 분포가
   질의마다 크게 다르기 때문이다('DDD' 최고 0.884 vs 'Anthropic' 최고 0.076).
   agent/selection의 유사도 컷과 같은 이유·같은 방식이다.

2. **신선도 하한** — 풀은 워커가 미리 채우는 창고라 자료가 늙는다. 뉴스형 토픽은
   오늘 소식이 중요하므로 하한을 짧게, 개념형은 길게 잡는다. 토픽 성격 판정은
   agent.assistant.features.topic_intent의 결과를 그대로 재사용한다(같은 판정을
   수집 창·신선도 감쇠와 공유해 기준이 갈라지지 않게 한다).

DB를 직접 보지 않는 순수 함수만 둔다. 발행일은 호출자가 조회해 주입한다
(report_builder는 infrastructure 경유로만 DB에 접근한다).
"""

from __future__ import annotations

import os
from collections.abc import Mapping, Sequence
from datetime import UTC, datetime, timedelta

from shared.report_models import ReportContextDocument

GLOBAL_NAMESPACE = "global"


def _env_int(name: str, default: int) -> int:
    """환경변수를 정수로 읽는다. 없거나 형식이 잘못되면 기본값을 반환한다."""
    try:
        return int(os.environ[name])
    except (KeyError, ValueError):
        return default


def _env_float(name: str, default: float) -> float:
    """환경변수를 실수로 읽는다. 없거나 형식이 잘못되면 기본값을 반환한다."""
    try:
        return float(os.environ[name])
    except (KeyError, ValueError):
        return default


# 풀 문서를 채택할 점수 하한 비율. cutoff = max(FLOOR, 최고점 × RATIO).
#
# 상대 비율만으로는 부족하다. 상대 컷은 "이번 검색 안에서 상대적으로 나은 것"을
# 고를 뿐이라, 풀에 쓸 만한 자료가 하나도 없으면 **잡음 중 상위**를 뽑는다.
# 실측(2026-07-28)에서 정확히 그 일이 벌어졌다 — 'Anthropic' 검색이 최고 0.076으로
# 5건을 통과시켰고, 그중에는 "암호화폐 버리고 AI로? 코인베이스 CEO"처럼 주제와
# 무관한 문서가 섞여 있었다. 그 결과 리포트가 일반론으로 얕아지고 사실과 다른
# 서술(OpenWiki 연계)까지 생성됐다.
POOL_SCORE_RATIO: float = _env_float("POOL_SCORE_RATIO", 0.75)

# 풀 문서를 채택할 **절대** 점수 하한. 이 아래는 "풀에 쓸 만한 자료가 없다"로 보고
# 실시간 수집으로 넘긴다.
#
# 점수는 `GREATEST(trigram similarity, ts_rank)` 합성값이며, 실측에서 두 무리로
# 뚜렷하게 갈렸다.
#
#   진짜 매칭   0.884  ('Domain-Driven Design' → SW공학 기사)
#   잡음        0.057 ~ 0.093  (Anthropic·ChatGPT·주가 검색 결과 전부)
#
# 약 10배 차이라 그 사이 어디에 그어도 두 무리는 갈린다. 0.35는 잡음 상단(0.093)의
# 약 4배, 확인된 매칭(0.884)의 절반 아래로 잡은 값이다.
#
# 주의: 근거가 두 무리·소수 표본이라 **잠정값**이다. 풀이 채워지면 점수 분포를 다시
# 재고 조정한다. 지금 풀(5개 키워드·48건)에서는 이 하한 때문에 사실상 항상 실시간
# 수집으로 가는데, 그것이 의도한 안전한 기본값이다 — 빈약한 창고를 믿느니 인터넷을
# 뒤지는 편이 낫다.
POOL_SCORE_FLOOR: float = _env_float("POOL_SCORE_FLOOR", 0.35)

# 실시간 수집을 생략하려면 컷오프를 통과한 풀 문서가 이만큼 있어야 한다.
# 생성 프롬프트 상한이 12건이고 개인 Wiki가 보통 4~5건을 채우므로, 3건이면
# 합쳐서 7~8건이 되어 근거로 부족하지 않다. 실측 후 조정 대상이다.
POOL_MIN_DOCUMENTS: int = _env_int("POOL_MIN_DOCUMENTS", 3)

# 풀 문서 신선도 하한(일). 뉴스형은 당일 소식이 중요하므로 짧게 잡아, 어제 채운
# 풀을 믿고 오늘 수집을 건너뛰는 일이 없게 한다.
POOL_MAX_AGE_DAYS_NEWS: int = _env_int("POOL_MAX_AGE_DAYS_NEWS", 1)

# 개념형 토픽의 신선도 하한. 개념·튜토리얼은 몇 달 전 자료도 유효하다
# (agent/selection의 EVERGREEN_WINDOW_DAYS와 같은 취지).
POOL_MAX_AGE_DAYS_EVERGREEN: int = _env_int("POOL_MAX_AGE_DAYS_EVERGREEN", 90)


def pool_max_age_days(topic_intent: str) -> int:
    """토픽 성격에 맞는 풀 신선도 하한(일)을 반환한다.

    Args:
        topic_intent: "evergreen"(개념형) 또는 그 외(뉴스형)

    Returns:
        이보다 오래된 풀 문서는 근거로 쓰지 않는다.
    """
    if topic_intent == "evergreen":
        return POOL_MAX_AGE_DAYS_EVERGREEN
    return POOL_MAX_AGE_DAYS_NEWS


def score_cutoff(best_score: float) -> float:
    """이번 풀 검색의 점수 컷을 계산한다 (절대 하한과 상대 비율 중 큰 값).

    두 기준이 각각 다른 실패를 막는다. 상대 비율은 "최고점에 한참 못 미치는 문서"를
    걸러내고, 절대 하한은 "최고점 자체가 형편없는 경우" 풀 전체를 포기하게 한다.

    Args:
        best_score: 이번 검색에서 관측된 최고 점수

    Returns:
        이 값 미만인 문서는 근거로 쓰지 않는다.
    """
    return max(POOL_SCORE_FLOOR, max(0.0, best_score) * POOL_SCORE_RATIO)


def select_pool_documents(
    documents: Sequence[ReportContextDocument],
    *,
    published_at: Mapping[str, datetime] | None = None,
    topic_intent: str = "news",
    now: datetime | None = None,
) -> list[ReportContextDocument]:
    """풀(global) 문서 중 근거로 쓸 만한 것만 골라 점수 내림차순으로 반환한다.

    개인 Wiki 문서(namespace_key != global)는 대상이 아니다 — 이 판정은 "실시간
    수집을 대체할 만한 풀 자료가 있는가"를 묻는 것이기 때문이다.

    Args:
        documents: prag_003이 반환한 개인·풀 혼합 문서 목록
        published_at: {document_version_id: 발행 시각}. 없으면 신선도 검사를
            건너뛴다(발행일을 모르는 문서를 그 이유만으로 버리지 않는다).
        topic_intent: 토픽 성격("news"|"evergreen"). 신선도 하한을 정한다.
        now: 기준 시각(테스트 주입용)

    Returns:
        컷오프와 신선도를 통과한 풀 문서 목록
    """
    pool = [
        document
        for document in documents
        if getattr(document, "namespace_key", "") == GLOBAL_NAMESPACE
    ]
    if not pool:
        return []

    cutoff = score_cutoff(max(float(getattr(d, "score", 0.0)) for d in pool))
    reference = now or datetime.now(UTC)
    horizon = reference - timedelta(days=pool_max_age_days(topic_intent))
    ages = published_at or {}

    selected: list[ReportContextDocument] = []
    for document in pool:
        if float(getattr(document, "score", 0.0)) < cutoff:
            continue
        published = ages.get(str(getattr(document, "document_version_id", "")))
        # 발행일을 모르면 신선도로 거르지 않는다. 풀 자료 상당수가 발행일 메타를
        # 갖지만, 없다는 이유로 버리면 쓸 수 있는 근거가 사라진다.
        if published is not None and published < horizon:
            continue
        selected.append(document)

    selected.sort(key=lambda d: float(getattr(d, "score", 0.0)), reverse=True)
    return selected


def is_pool_sufficient(pool_documents: Sequence[ReportContextDocument]) -> bool:
    """풀 자료만으로 리포트를 쓸 수 있는지 판정한다.

    True면 호출자는 실시간 수집을 생략해도 된다.
    """
    return len(pool_documents) >= POOL_MIN_DOCUMENTS
