"""개인 LLM Wiki 계정 단위 초기화 기능 구현."""

from typing import Mapping, Protocol


class PersonalWikiResetWriter(Protocol):
    """개인 LLM Wiki 초기화에 필요한 영속 저장소 경계."""

    async def reset_wiki(
        self, user_id: str, *, request_id: str
    ) -> Mapping[str, object]:
        """사용자의 개인 LLM Wiki 파생 상태를 초기화한다."""
        ...


# MVP: agent-api-mvp-scope.md에서 구현 대상으로 지정된 기능입니다.
async def pwiki_013(
    writer: PersonalWikiResetWriter,
    user_id: str,
    *,
    request_id: str,
) -> Mapping[str, object]:
    """[PWIKI-013] 사용자 원본을 보존하고 개인 LLM Wiki를 초기화한다."""
    if not user_id:
        raise ValueError("PWIKI-013에 user_id가 필요합니다.")
    if not request_id:
        raise ValueError("PWIKI-013에 request_id가 필요합니다.")
    return await writer.reset_wiki(user_id, request_id=request_id)
