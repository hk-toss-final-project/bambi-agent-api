"""기능 구현 모듈.

AUTH-006 기능의 실제 구현 위치를 제공한다.
"""

from shared.contracts import FeatureRequest, FeatureResult


async def auth_006(request: FeatureRequest) -> FeatureResult:
    """[AUTH-006] 내부 요청 서명 검증.

    내부 요청의 위변조와 재전송을 방지한다.
    """
    raise NotImplementedError("[AUTH-006] 기능 구현이 필요합니다.")
