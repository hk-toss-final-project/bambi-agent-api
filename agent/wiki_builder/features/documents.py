"""기능 구현 모듈.

WBA-003, WBA-004, WBA-005 기능의 실제 구현 위치를 제공한다.
"""

from shared.contracts import FeatureRequest, FeatureResult


async def wba_003(request: FeatureRequest) -> FeatureResult:
    """[WBA-003] Wiki 문서 정규화.

    입력 데이터를 개인 Wiki 문서 구조로 정리한다.
    """
    raise NotImplementedError("[WBA-003] 기능 구현이 필요합니다.")


async def wba_004(request: FeatureRequest) -> FeatureResult:
    """[WBA-004] Wiki 문서 중복 제거.

    동일하거나 유사한 사용자 지식을 제거한다.
    """
    raise NotImplementedError("[WBA-004] 기능 구현이 필요합니다.")


async def wba_005(request: FeatureRequest) -> FeatureResult:
    """[WBA-005] Wiki 문서 병합.

    관련 문서와 메모를 하나의 지식으로 통합한다.
    """
    raise NotImplementedError("[WBA-005] 기능 구현이 필요합니다.")
