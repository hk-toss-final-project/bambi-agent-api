"""기능 구현 모듈.

SCH-009, SCH-010 기능의 실제 구현 위치를 제공한다.
"""

from shared.contracts import FeatureRequest, FeatureResult


async def sch_009(request: FeatureRequest) -> FeatureResult:
    """[SCH-009] 사용자 Wiki 재구성 스케줄.

    변경이 누적된 사용자의 Wiki를 재구성한다.
    """
    raise NotImplementedError("[SCH-009] 기능 구현이 필요합니다.")


async def sch_010(request: FeatureRequest) -> FeatureResult:
    """[SCH-010] 사용자 관심사 재계산.

    개인 Wiki 변경에 따라 관심사 프로필을 재계산한다.
    """
    raise NotImplementedError("[SCH-010] 기능 구현이 필요합니다.")
