"""Global Source 검색을 에이전트 Tool로 노출하는 함수."""


# MVP: BAMBI-005 Global Source 검색 단계에서 구현합니다.
async def search_global_source_tool(
    query: str,
    top_k: int = 10,
) -> list[dict[str, object]]:
    """최신 외부 자료를 Global Source Pool에서 검색한다.

    Args:
        query: Global Source Pool에서 찾을 검색어
        top_k: 반환할 최대 검색 결과 수

    Returns:
        최신성, 관련도와 출처 정보가 포함된 검색 결과
    """
    raise NotImplementedError("Global Source 검색 Tool 구현이 필요합니다.")
