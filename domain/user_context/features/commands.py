"""기능 구현 모듈.

CTX-001, CTX-002, CTX-004 기능의 실제 구현 위치를 제공한다.
"""

from shared.contracts import FeatureRequest, FeatureResult


async def ctx_001(request: FeatureRequest) -> FeatureResult:
    """[CTX-001] 사용자 컨텍스트 등록.

    AI 처리에 필요한 최소 사용자 컨텍스트를 등록한다.
    """
    raise NotImplementedError("[CTX-001] 기능 구현이 필요합니다.")


async def ctx_002(request: FeatureRequest) -> FeatureResult:
    """[CTX-002] 사용자 컨텍스트 갱신.

    관심사, 플랜, 언어 설정 등의 변경을 반영한다.
    """
    raise NotImplementedError("[CTX-002] 기능 구현이 필요합니다.")


async def ctx_004(request: FeatureRequest) -> FeatureResult:
    """[CTX-004] 사용자 컨텍스트 삭제.

    탈퇴 또는 삭제 요청 시 컨텍스트를 제거한다.
    """
    raise NotImplementedError("[CTX-004] 기능 구현이 필요합니다.")
