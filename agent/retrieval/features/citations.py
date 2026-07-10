"""기능 구현 모듈.

RET-008 기능의 실제 구현 위치를 제공한다.
"""

from shared.contracts import FeatureRequest, FeatureResult


async def ret_008(request: FeatureRequest) -> FeatureResult:
    """[RET-008] Citation 설정.

    출처 표시와 검증 정책을 설정한다.
    """
    raise NotImplementedError("[RET-008] 기능 구현이 필요합니다.")
