"""Report Builder가 쓰는 실시간 외부 자료 수집·선별 어댑터.

Report Builder는 그동안 DB에 저장된 개인 Wiki 문서만 근거로 썼다(REPORT-005는
개인 Wiki 결과를 그대로 통과시키는 패스스루였다). 그래서 "관심 키워드의 최신
자료로 콘텐츠를 만든다"는 목표와 실제 동작이 갈라져 있었다.

이 모듈은 검증된 키워드 비서(agent/assistant)의 수집·선별을 Report Builder의
근거 문서로 변환한다. 로직을 복사하지 않고 `assist_daily_agent`를 **호출**하므로
두 파이프라인이 같은 코드를 공유한다 — 비서 UI와 Main API의 결과가 갈라지지
않는 것이 이 설계의 목적이다.

경계:
- 여기서는 수집·형식 변환만 한다. 스코어링·클러스터링·중복 제거는 비서 쪽
  결정적 파이프라인이 이미 수행했으므로 다시 계산하지 않는다.
- LLM 판단(검색어 재구성·재시도)도 비서 에이전트가 담당한다.
- **검색어 확장을 켜는 곳은 여기다.** 관심 키워드 하나로만 수집하면 '코스피'
  리포트에 코스닥시장 기사가 안 걸린다. 개인 Wiki에서 그 키워드와 연결된 이웃
  노드를 보조 검색어로 함께 던진다. 아침 보고서(브리핑)는 켜지 않는다 —
  확장 여부를 비서 파이프라인 안이 아니라 **호출자**가 정하는 이유다.
- 이웃 **조회는 여기서 하지 않는다.** 이 함수는 DB 연결이 없는 동기 함수라
  (그래프가 to_thread로 부른다), 조회는 연결을 가진 load_context 노드가 하고
  결과만 인자로 받는다.
"""

from __future__ import annotations

import logging
import os
from collections.abc import Sequence

from agent.assistant.api import assist_daily_agent
from domain.interests.api import expand_topic_queries
from shared.report_models import ReportContextDocument

logger = logging.getLogger("agent.report_builder.live_sources")

# 리포트 생성에 붙일 보조 검색어 상한. 온디맨드 리포트가 "고른 주제 하나 +
# Wiki에서 연결된 상위 태그"를 엮는 경로라, 루트 1 + 이웃 3으로 맞춘다
# (2026-08-10 계약: 온디맨드 = 단일 주제 + Wiki 이웃 확장).
#
# 앞선 값 2는 "수집이 검색어 수에 거의 비례한다"는 제약 때문이었다.
# **그 비례는 지금도 유효하다.** 소스 축을 동시에 부르도록 바꿨지만
# (agent/assistant/features/pipeline.collect_documents) 상쇄되지 않았다.
#
#   2026-08-10 실측 (소스 병렬, 순서 교차 2라운드)
#     검색어 1개   31.1초
#     검색어 3개   92.0초   → 2.96x, 여전히 개수에 정비례
#
# 소스 병렬화가 준 것은 15%뿐이다(검색어 3개 기준 110.5초 → 93.5초). 병렬 시간은
# max(뉴스, YouTube, Reddit)인데 **뉴스가 전체의 85% 가까이**를 차지해서다. 뉴스는
# 이미 내부에서 Provider 3개를 동시 호출하므로 바깥 축을 넓혀도 더 줄지 않는다.
#
# 그래도 3을 쓴다. 수집 92초 + LLM 단계를 더해도 Worker lease(600초)에 여유가
# 크고, 온디맨드 계약이 요구하는 태그 수가 3이기 때문이다.
#
# 0으로 두면 확장이 완전히 꺼져 이전 동작(검색어 1개)으로 돌아간다 — 같은
# 데이터에서 A/B 비교를 하기 위한 스위치다.
_DEFAULT_EXPANSION_LIMIT = 3

# Wiki 이웃을 DB에서 미리 가져올 때 상한에 더할 여유분. 원 토픽과 겹치는 이웃이
# 걸러지므로, 딱 상한만큼만 가져오면 자리가 비게 된다.
_RELATED_FETCH_MARGIN = 3


def _expansion_limit() -> int:
    """보조 검색어 상한을 환경변수에서 읽는다. 없거나 형식이 틀리면 기본값."""
    try:
        return int(os.environ["REPORT_QUERY_EXPANSION_LIMIT"])
    except (KeyError, ValueError):
        return _DEFAULT_EXPANSION_LIMIT


def related_keyword_fetch_limit() -> int:
    """개인 Wiki 그래프에서 조회할 이웃 키워드 수를 반환한다.

    확장이 꺼져 있으면(상한 0 이하) 0을 반환해, 호출자가 DB 조회 자체를 건너뛸
    수 있게 한다.

    Returns:
        조회할 이웃 수. 확장이 꺼져 있으면 0.
    """
    limit = _expansion_limit()
    return limit + _RELATED_FETCH_MARGIN if limit > 0 else 0


# 생성 프롬프트에 넣을 근거 문서 수 상한. 개인 Wiki와 실시간 자료를 합친 뒤 적용한다.
_DEFAULT_MAX_DOCUMENTS = 12

# 실시간 자료의 namespace_key. 개인 Wiki 문서와 출처를 구분하는 데 쓴다.
_LIVE_NAMESPACE = "live-source"


def _to_context_document(item: dict[str, object], number: int) -> ReportContextDocument | None:
    """비서 선별 아이템 하나를 Report Builder 근거 문서로 변환한다.

    참조 ID는 개인 Wiki(P1)·Global(G1)과 같은 체계의 `L{n}`을 쓴다. 생성 프롬프트가
    `[P1]`/`[G1]`/`[L1]` 형식만 허용하므로, 다른 형식을 쓰면 LLM이 존재하지 않는
    참조를 만들어 Citation 검증에서 실패한다.

    Args:
        item: assist_daily_agent 결과의 items 원소
        number: 참조 ID(L{n})에 쓸 1부터 시작하는 순번

    Returns:
        변환된 근거 문서. 제목과 본문이 모두 비거나 출처 URL이 없으면 None.
    """
    title = str(item.get("title") or "").strip()
    summary = str(item.get("summary") or "").strip()
    if not title and not summary:
        return None

    sources = [s for s in (item.get("sources") or []) if isinstance(s, dict)]
    primary_url = str(sources[0].get("url") or "") if sources else ""
    # 실시간 자료는 Wiki 문서 Version이 없어서 Citation 저장 시 URL이 유일한 출처
    # 증빙이다(agent.citations는 document_version_id 또는 url을 요구한다).
    if not primary_url:
        return None

    # 통합 요약 본문에 실제 출처 목록을 덧붙여, 생성 단계가 근거를 인용할 수 있게 한다.
    source_lines = "\n".join(
        f"- {s.get('source_type')}: {s.get('title')} ({s.get('url')})" for s in sources
    )
    content = f"{summary}\n\n[출처]\n{source_lines}".strip() if source_lines else summary

    try:
        score = float(item.get("score") or 0.0)
    except (TypeError, ValueError):
        score = 0.0

    return ReportContextDocument(
        reference=f"L{number}",
        document_version_id="",
        chunk_id=f"L{number}",
        namespace_key=_LIVE_NAMESPACE,
        title=title or summary[:60],
        content=content,
        url=primary_url,
        score=score,
    )


def collect_live_context(
    topic: str,
    user_id: str,
    *,
    model: str = "gpt-4.1-mini",
    related_keywords: Sequence[str] = (),
) -> list[ReportContextDocument]:
    """[REPORT-005 구현] 키워드로 실시간 외부 자료를 수집·선별해 근거 문서로 반환한다.

    키워드 비서 에이전트(수집 → 임베딩 유사도 필터 → 클러스터링 → 스코어링 →
    최근 7일 중복 제거 → 부족하면 검색어 재구성 후 재시도)를 그대로 실행한다.

    수집에 실패해도 예외를 올리지 않는다 — 실시간 자료가 없다고 해서 개인 Wiki
    기반 생성까지 막을 이유는 없기 때문이다. 실패는 로그로 남기고 빈 목록을 준다.

    Args:
        topic: 콘텐츠 주제(키워드)
        user_id: 사용자 식별자. 비서의 중복 제거·개인화 이력에 쓰인다.
        model: 비서가 요약·판단에 쓸 OpenAI 모델
        related_keywords: 개인 Wiki 그래프에서 이 토픽과 연결된 이웃 키워드
            (연결 강도 내림차순). 호출자가 조회해 넘기며, 비면 기존과 똑같이
            검색어 하나로 수집한다.

    Returns:
        점수 내림차순 근거 문서 목록. 수집 실패 시 빈 목록.
    """
    # 이웃 키워드를 보조 검색어로 만든다. LLM도 DB도 부르지 않는 결정적 계산이라
    # 실패 경로가 없고, 이웃이 없는 고립 토픽이면 확장이 0개로 나와 기존과
    # 똑같이 검색어 하나로 동작한다.
    expansion = expand_topic_queries(
        topic, related_keywords=related_keywords, limit=_expansion_limit()
    )
    if expansion.expanded:
        logger.info("검색어 확장 %s → %s", topic, list(expansion.expanded))
    else:
        logger.info("검색어 확장 없음 (topic=%s, reason=%s)", topic, expansion.reason)

    try:
        # 근거(items)만 쓰고 브리핑 Markdown은 버리므로 보고서를 만들지 않는다.
        # 이력도 기록하지 않는다 — 리포트 생성이 사용자의 일간 브리핑에서 같은
        # 소식을 7일간 가려버리는 이력 오염을 막기 위해서다.
        result = assist_daily_agent(
            topic,
            user_id=user_id,
            model=model,
            extra_queries=expansion.expanded,
            record_history=False,
            include_report=False,
        )
    except Exception as error:
        logger.warning("실시간 자료 수집 실패, 개인 Wiki만 사용한다: %s", error)
        return []

    documents: list[ReportContextDocument] = []
    for item in result.get("items") or []:
        if not isinstance(item, dict):
            continue
        # 순번은 수락된 문서 기준으로 매겨 참조 ID(L1, L2, …)에 빈 번호가 없게 한다.
        document = _to_context_document(item, len(documents) + 1)
        if document is not None:
            documents.append(document)

    logger.info(
        "실시간 자료 %d건 수집 (mode=%s, 시도 검색어=%s)",
        len(documents),
        result.get("mode"),
        result.get("attempts"),
    )
    return documents


def select_generation_context(
    personal: Sequence[ReportContextDocument],
    live: Sequence[ReportContextDocument],
    *,
    max_documents: int = _DEFAULT_MAX_DOCUMENTS,
) -> list[ReportContextDocument]:
    """[REPORT-006 구현] 개인 Wiki 문서와 실시간 자료를 합쳐 생성에 쓸 근거를 고른다.

    개인 Wiki 문서를 앞에 둔다. 사용자의 기존 맥락이 콘텐츠의 관점을 정하고,
    실시간 자료는 그 관점에 최신 근거를 붙이는 역할이기 때문이다. 같은 참조 ID가
    중복되면 먼저 온 쪽을 남긴다.

    Args:
        personal: 개인 Wiki 검색·구성 결과
        live: 실시간 외부 자료
        max_documents: 생성 프롬프트에 넣을 최대 문서 수

    Returns:
        중복을 제거하고 상한을 적용한 근거 문서 목록
    """
    ordered_live = sorted(live, key=lambda d: getattr(d, "score", 0.0), reverse=True)
    selected: list[ReportContextDocument] = []
    seen: set[str] = set()
    for document in [*personal, *ordered_live]:
        # 참조 ID가 없는 형태(테스트 더미 등)도 그대로 통과시키되 중복만 거른다.
        key = str(getattr(document, "reference", None) or document)
        if key in seen:
            continue
        seen.add(key)
        selected.append(document)
        if len(selected) >= max_documents:
            break
    return selected
