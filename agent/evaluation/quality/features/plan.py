"""기능 구현 모듈.

QUALITY-012 기능의 실제 구현 위치를 제공한다.
"""

from shared.contracts import FeatureRequest, FeatureResult


async def quality_012(request: FeatureRequest) -> FeatureResult:
    """[QUALITY-012] 플랜 정책 적합성.

    생성 결과가 해당 플랜의 형식과 범위에 맞는지 확인한다.
    """
    raise NotImplementedError("[QUALITY-012] 기능 구현이 필요합니다.")
