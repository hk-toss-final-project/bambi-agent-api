"""기능 구현 모듈.

COL-005 기능의 실제 구현 위치를 제공한다.

수집 대상 SNS는 YouTube와 Reddit이다. 두 Provider 구현은 이미
`features/youtube.py`·`features/reddit.py`에 있으므로(키워드 비서가 쓰던 것),
이 기능은 뉴스 커넥터(COL-001~004)와 같은 방식으로 그 Provider를 호출하는
얇은 연결만 담당한다. 둘 다 자격 증명이 필요 없다.
"""

from infrastructure.sources.connectors.features.latest import (
    LatestArticle,
    LatestInformationProvider,
    LatestProviderError,
)

# 이 기능이 수집을 위임할 SNS Provider 이름.
SNS_PROVIDERS = ("youtube", "reddit")


# MVP: agent-api-mvp-scope.md에서 구현 대상으로 지정된 기능입니다.
async def col_005(
    provider: LatestInformationProvider,
    *,
    query: str,
    limit: int,
    language: str | None = None,
) -> list[LatestArticle]:
    """[COL-005] SNS 수집.

    허용된 SNS 공개 데이터를 수집한다. YouTube 영상 검색과 Reddit 공개 RSS
    검색을 같은 최신 문서 구조로 돌려주며, 어느 Provider를 쓸지는 호출자가
    넘긴 Provider 인스턴스가 결정한다.
    """
    if provider.name not in SNS_PROVIDERS:
        raise LatestProviderError(
            provider.name,
            "provider_mismatch",
            f"COL-005에는 SNS Provider({', '.join(SNS_PROVIDERS)})가 필요합니다.",
        )
    return await provider.search(query=query, limit=limit, language=language)
