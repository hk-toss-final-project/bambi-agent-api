"""개인 Wiki Build Version 조회 기능 구현."""

from typing import Mapping, Protocol


class WikiVersionReader(Protocol):
    """개인 Wiki Build Version 조회에 필요한 영속 저장소 경계."""

    async def get_wiki_version(
        self, user_id: str, wiki_version_id: str
    ) -> Mapping[str, object] | None:
        """특정 Wiki Build Snapshot을 반환한다."""
        ...


# MVP: agent-api-mvp-scope.md에서 구현 대상으로 지정된 기능입니다.
async def pwiki_006(
    reader: WikiVersionReader, user_id: str, wiki_version_id: str
) -> Mapping[str, object] | None:
    """[PWIKI-006] 개인 Wiki 문서 버전 관리.

    문서 변경 이력을 버전으로 관리한다.
    """
    if not user_id:
        raise ValueError("PWIKI-006에 user_id가 필요합니다.")
    if not wiki_version_id:
        raise ValueError("PWIKI-006에 wiki_version_id가 필요합니다.")
    return await reader.get_wiki_version(user_id, wiki_version_id)
