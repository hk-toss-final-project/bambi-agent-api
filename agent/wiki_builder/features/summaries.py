"""기능 구현 모듈.

WBA-008, WBA-009, WBA-010 기능의 실제 구현 위치를 제공한다.
"""

from shared.contracts import FeatureRequest, FeatureResult


async def wba_008(request: FeatureRequest) -> FeatureResult:
    """[WBA-008] Wiki Summary 생성.

    관심사 그룹별 개인 Wiki 요약을 생성한다.
    """
    raise NotImplementedError("[WBA-008] 기능 구현이 필요합니다.")


async def wba_009(request: FeatureRequest) -> FeatureResult:
    """[WBA-009] Interaction Memory 생성.

    사용자와 콘텐츠의 의미 있는 대화를 지식으로 정리한다.
    """
    raise NotImplementedError("[WBA-009] 기능 구현이 필요합니다.")


async def wba_010(request: FeatureRequest) -> FeatureResult:
    """[WBA-010] 오래된 Memory 압축.

    누적된 상호작용 Memory를 압축하고 병합한다.
    """
    raise NotImplementedError("[WBA-010] 기능 구현이 필요합니다.")
