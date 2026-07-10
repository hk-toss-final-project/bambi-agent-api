"""기능 구현 모듈.

WBA-017 기능의 실제 구현 위치를 제공한다.
"""

from shared.contracts import FeatureRequest, FeatureResult


async def wba_017(request: FeatureRequest) -> FeatureResult:
    """[WBA-017] 외부 데이터 자동 편입 차단.

    자동 수집 자료가 사용자 선택 없이 개인 Wiki에 들어가지 않도록 한다.
    """
    raise NotImplementedError("[WBA-017] 기능 구현이 필요합니다.")
