"""Wiki Builder의 관심사 관련 기능 스캐폴드.

관심 키워드 추출 로직은 INT-001 소유 영역인
domain/interests/features/extraction.py로 이동했다. 이 모듈은 Wiki 문서
분류·구조 재구성(WBA-006, WBA-007) 기능의 구현 위치만 유지한다.
"""

from shared.contracts import FeatureRequest, FeatureResult


async def wba_006(request: FeatureRequest) -> FeatureResult:
    """[WBA-006] Wiki 관심사 분류.

    개인 Wiki 문서를 관심사별로 분류한다.
    """
    raise NotImplementedError("[WBA-006] 기능 구현이 필요합니다.")


async def wba_007(request: FeatureRequest) -> FeatureResult:
    """[WBA-007] Wiki 관심사 구조 재구성.

    관심사 계층과 관계를 다시 구성한다.
    """
    raise NotImplementedError("[WBA-007] 기능 구현이 필요합니다.")
