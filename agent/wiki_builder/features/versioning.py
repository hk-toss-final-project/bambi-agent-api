"""기능 구현 모듈.

WBA-012, WBA-013 기능의 실제 구현 위치를 제공한다.
"""

from shared.contracts import FeatureRequest, FeatureResult


async def wba_012(request: FeatureRequest) -> FeatureResult:
    """[WBA-012] Wiki 버전 생성.

    재구성된 Wiki 상태를 새 버전으로 저장한다.
    """
    raise NotImplementedError("[WBA-012] 기능 구현이 필요합니다.")


async def wba_013(request: FeatureRequest) -> FeatureResult:
    """[WBA-013] Wiki 변경점 생성.

    이전 버전과 변경된 내용을 기록한다.
    """
    raise NotImplementedError("[WBA-013] 기능 구현이 필요합니다.")
