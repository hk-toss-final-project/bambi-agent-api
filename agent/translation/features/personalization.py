"""기능 구현 모듈.

TR-006 기능의 실제 구현 위치를 제공한다.
"""

from shared.contracts import FeatureRequest, FeatureResult


async def tr_006(request: FeatureRequest) -> FeatureResult:
    """[TR-006] 사용자 선호 언어 반영.

    사용자의 기본 언어 설정을 번역에 적용한다.
    """
    raise NotImplementedError("[TR-006] 기능 구현이 필요합니다.")
