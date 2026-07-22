"""개인 Wiki Source Event 멱등 식별자 생성 기능 구현."""


# MVP: agent-api-mvp-scope.md에서 구현 대상으로 지정된 기능입니다.
async def wse_011(user_id: str, source_event_id: str) -> str:
    """[WSE-011] 이벤트 중복 처리 방지.

    동일 사용자 이벤트의 중복 처리를 방지한다.
    """
    if not user_id or not source_event_id:
        raise ValueError("WSE-011에 user_id와 source_event_id가 필요합니다.")
    return f"{user_id}:{source_event_id}"
