"""기능 구현 모듈.

SCH-011, SCH-012 기능의 실제 구현 위치를 제공한다.
"""

from shared.contracts import FeatureRequest, FeatureResult


async def sch_011(request: FeatureRequest) -> FeatureResult:
    """[SCH-011] 콘텐츠 생성 스케줄.

    일간·주간 개인화 콘텐츠 생성 작업을 등록한다.
    """
    raise NotImplementedError("[SCH-011] 기능 구현이 필요합니다.")


async def sch_012(request: FeatureRequest) -> FeatureResult:
    """[SCH-012] 추천 갱신 스케줄.

    사용자별 추천 후보 갱신 작업을 등록한다.
    """
    raise NotImplementedError("[SCH-012] 기능 구현이 필요합니다.")
