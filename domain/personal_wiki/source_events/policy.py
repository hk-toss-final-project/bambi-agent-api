"""기능 구현 모듈.

WSE-012 기능의 실제 구현 위치를 제공한다.
"""

from shared.contracts import FeatureRequest, FeatureResult


async def wse_012(request: FeatureRequest) -> FeatureResult:
    """[WSE-012] Wiki 편입 정책 판단.

    사용자 행동을 Wiki 문서 또는 관심사 신호로 분류한다.
    """
    raise NotImplementedError("[WSE-012] 기능 구현이 필요합니다.")
