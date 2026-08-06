"""관심 키워드를 개인 Wiki에서 연결된 키워드로 넓히는 검색어 확장.

리포트 생성이 관심 키워드 문자열 **하나**로만 외부 자료를 모아, '코스피'로
리포트를 만들면 제목에 '코스피'가 든 기사만 걸렸다. 그런데 그 연결 정보는 이미
DB에 있다 — Wiki Builder가 문서를 만들면서 노드 간 관계를 추출해 두었다.

    코스피 --[entity_relation]--> 코스닥시장

이웃 조회는 DB 계층이 하고(``list_related_wiki_keywords``) 이 모듈은 그 결과를
검색어 목록으로 다듬는다. 원 토픽과 겹치거나 서로 중복인 것을 걸러내고 상한을
적용하는, LLM도 DB도 부르지 않는 결정적 함수다.

확장 범위는 **1홉**으로 제한한다. 2홉은 주제가 흐려지고 비용이 제곱으로 는다.
설계 근거는 [docs/wiki-graph-query-expansion.md](../../../docs/wiki-graph-query-expansion.md)
§4의 결정표를 따른다.

채점은 넓히지 않는다 — 확장은 **수집만** 넓히고, 유사도·중복·이력 판정은 원
토픽 기준을 그대로 쓴다(pipeline.run_daily의 keyword/search_query 분리).
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass

# 확장 검색어 기본 상한. 수집은 소스 3개를 검색어마다 호출하므로 검색어를 N개로
# 늘리면 수집 시간이 대략 N배가 된다(실측: 검색어 1개 리포트 41.5초). Worker
# lease 600초 안에 넉넉히 들어오도록 2개를 기본으로 둔다 — 총 3개 검색어.
DEFAULT_EXPANSION_LIMIT = 2

# 확장 결과에 남기는 사유 코드. 로그에서 "왜 안 넓어졌는지"를 문자열 파싱 없이 본다.
REASON_EXPANDED = "expanded"
REASON_NO_NEIGHBORS = "no_neighbors"  # Wiki에 이웃이 없는 고립 노드
REASON_DISABLED = "disabled"  # 상한이 0 이하 — 확장을 끈 상태


@dataclass(frozen=True, slots=True)
class QueryExpansion:
    """토픽 하나를 넓힌 결과.

    ``queries``의 첫 항목은 항상 원 토픽이다. 확장이 하나도 안 붙어도 호출자가
    분기 없이 그대로 수집에 넘길 수 있어야 하기 때문이다.
    """

    topic: str
    queries: tuple[str, ...]
    expanded: tuple[str, ...]
    reason: str


def _normalize(value: str) -> str:
    """비교용으로 대소문자·앞뒤 공백·구분 기호 차이를 없앤다.

    Wiki 노드 키는 '코스닥-시장'처럼 하이픈으로 이어지고 제목은 공백으로 떨어져
    있어, 같은 이름을 다르게 취급하지 않도록 구분 기호를 공백으로 맞춘다.
    """
    replaced = value.replace("-", " ").replace("_", " ")
    return " ".join(replaced.split()).casefold()


def expand_topic_queries(
    topic: str,
    *,
    related_keywords: Sequence[str] = (),
    limit: int = DEFAULT_EXPANSION_LIMIT,
) -> QueryExpansion:
    """관심 토픽과 Wiki 이웃 키워드를 합쳐 수집에 쓸 검색어 목록을 만든다.

    이웃은 연결 강도 내림차순으로 들어온다고 보고 순서를 그대로 유지한다. 원
    토픽과 같은 뜻이 되는 키워드(대소문자·공백·하이픈만 다른 경우)는 같은 검색을
    두 번 하는 셈이라 건너뛴다.

    Args:
        topic: 사용자 관심 토픽 (예: "코스피")
        related_keywords: 개인 Wiki 그래프에서 조회한 이웃 키워드. 조회에
            실패했거나 이웃이 없으면 빈 목록을 넘긴다.
        limit: 더할 보조 검색어의 최대 개수. 0 이하면 확장하지 않는다.

    Returns:
        원 토픽을 첫 항목으로 갖는 검색어 목록과 그 근거.

    Raises:
        ValueError: 토픽이 비어 있는 경우
    """
    normalized_topic = topic.strip()
    if not normalized_topic:
        raise ValueError("확장할 토픽이 비어 있습니다.")

    base = (normalized_topic,)
    if limit <= 0:
        return QueryExpansion(
            topic=normalized_topic,
            queries=base,
            expanded=(),
            reason=REASON_DISABLED,
        )

    seen = {_normalize(normalized_topic)}
    expanded: list[str] = []
    for keyword in related_keywords:
        if len(expanded) >= limit:
            break
        candidate = keyword.strip()
        if not candidate:
            continue
        marker = _normalize(candidate)
        if marker in seen:
            continue
        seen.add(marker)
        expanded.append(candidate)

    return QueryExpansion(
        topic=normalized_topic,
        queries=(*base, *tuple(expanded)),
        expanded=tuple(expanded),
        reason=REASON_EXPANDED if expanded else REASON_NO_NEIGHBORS,
    )
