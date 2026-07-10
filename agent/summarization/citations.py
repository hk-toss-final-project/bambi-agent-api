"""기능 구현 모듈.

SUM-011 기능의 실제 구현 위치를 제공한다.
"""

from shared.contracts import FeatureRequest, FeatureResult


async def sum_011(request: FeatureRequest) -> FeatureResult:
    """[SUM-011] Citation 포함 요약.

    요약 내용에 참조한 출처를 연결한다.
    """
    raise NotImplementedError("[SUM-011] 기능 구현이 필요합니다.")
