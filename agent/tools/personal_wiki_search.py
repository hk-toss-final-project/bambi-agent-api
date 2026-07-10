"""개인 Wiki 검색을 에이전트 Tool로 노출하는 함수."""


# MVP: PRAG-003 Hybrid Search 단계에서 구현합니다.
async def search_personal_wiki_tool(
    user_id: str,
    query: str,
    top_k: int = 5,
) -> list[dict[str, object]]:
    """사용자 범위를 강제한 개인 Wiki Hybrid Search를 수행한다.

    Args:
        user_id: 검색 범위를 제한할 사용자 식별자
        query: 개인 Wiki에서 찾을 검색어
        top_k: 반환할 최대 검색 결과 수

    Returns:
        점수와 출처 정보가 포함된 개인 Wiki 검색 결과
    """
    raise NotImplementedError("개인 Wiki 검색 Tool 구현이 필요합니다.")
