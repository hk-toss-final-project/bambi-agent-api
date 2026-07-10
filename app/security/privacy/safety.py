"""기능 구현 모듈.

SEC-011 기능의 실제 구현 위치를 제공한다.
"""

from shared.contracts import FeatureRequest, FeatureResult


async def sec_011(request: FeatureRequest) -> FeatureResult:
    """[SEC-011] 생성 결과 안전성 검사.

    정책 위반 콘텐츠의 생성과 발행을 차단한다.
    """
    raise NotImplementedError("[SEC-011] 기능 구현이 필요합니다.")
