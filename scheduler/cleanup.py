"""기능 구현 모듈.

SCH-014, SCH-015 기능의 실제 구현 위치를 제공한다.
"""

from shared.contracts import FeatureRequest, FeatureResult


async def sch_014(request: FeatureRequest) -> FeatureResult:
    """[SCH-014] 로그 정리 스케줄.

    보존 기간이 지난 로그를 정리한다.
    """
    raise NotImplementedError("[SCH-014] 기능 구현이 필요합니다.")


async def sch_015(request: FeatureRequest) -> FeatureResult:
    """[SCH-015] 오래된 데이터 정리.

    만료된 Source와 생성 후보를 정리한다.
    """
    raise NotImplementedError("[SCH-015] 기능 구현이 필요합니다.")
