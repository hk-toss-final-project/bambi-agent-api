"""개인 Wiki 동일 내용 문서 중복 판정 기능 구현."""

from collections.abc import Mapping


# MVP: agent-api-mvp-scope.md에서 구현 대상으로 지정된 기능입니다.
async def pwiki_008(
    head: Mapping[str, object] | None,
    duplicate: Mapping[str, object] | None,
) -> Mapping[str, object] | None:
    """[PWIKI-008] Wiki 문서 중복 제거.

    동일하거나 유사한 개인 Wiki 문서를 중복 제거한다.
    """
    if head is not None and duplicate is not None and duplicate.get("id") == head.get("id"):
        return None
    return duplicate
