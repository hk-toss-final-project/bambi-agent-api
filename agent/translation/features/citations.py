"""기능 구현 모듈.

TR-008 기능의 실제 구현 위치를 제공한다.
"""

from shared.contracts import FeatureRequest, FeatureResult


async def tr_008(request: FeatureRequest) -> FeatureResult:
    """[TR-008] Citation 유지.

    번역 후에도 원문 출처 연결을 유지한다.
    """
    raise NotImplementedError("[TR-008] 기능 구현이 필요합니다.")
