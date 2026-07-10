"""기능 구현 모듈.

CTYPE-010, CTYPE-011 기능의 실제 구현 위치를 제공한다.
"""

from shared.contracts import FeatureRequest, FeatureResult


async def ctype_010(request: FeatureRequest) -> FeatureResult:
    """[CTYPE-010] 기존 콘텐츠 후속 콘텐츠.

    이전 콘텐츠의 후속 변화와 업데이트를 생성한다.
    """
    raise NotImplementedError("[CTYPE-010] 기능 구현이 필요합니다.")


async def ctype_011(request: FeatureRequest) -> FeatureResult:
    """[CTYPE-011] 사용자 질문 기반 콘텐츠.

    사용자의 질문을 중심으로 맞춤 콘텐츠를 생성한다.
    """
    raise NotImplementedError("[CTYPE-011] 기능 구현이 필요합니다.")
