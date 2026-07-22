"""Global Source와 개인 Wiki Namespace 격리 기능 구현."""


# MVP: agent-api-mvp-scope.md에서 구현 대상으로 지정된 기능입니다.
async def gsp_015(namespace_key: str) -> None:
    """[GSP-015] 개인 Wiki 자동 반영 금지.

    수집 데이터를 사용자 선택 없이 개인 Wiki에 반영하지 않는다.
    """
    if namespace_key != "global":
        raise ValueError("GSP-015는 Global Namespace에만 수집 문서를 저장할 수 있습니다.")
