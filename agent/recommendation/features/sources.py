"""기능 구현 모듈.

REC-001, REC-002, REC-003, REC-004, REC-005, REC-006, REC-007, REC-008 기능의 실제 구현 위치를 제공한다.
"""

from shared.contracts import FeatureRequest, FeatureResult


async def rec_001(request: FeatureRequest) -> FeatureResult:
    """[REC-001] 관심사 기반 추천.

    사용자 관심사 프로필에 맞는 콘텐츠를 추천한다.
    """
    raise NotImplementedError("[REC-001] 기능 구현이 필요합니다.")


async def rec_002(request: FeatureRequest) -> FeatureResult:
    """[REC-002] 개인 Wiki 기반 추천.

    사용자가 저장한 지식과 유사한 자료를 추천한다.
    """
    raise NotImplementedError("[REC-002] 기능 구현이 필요합니다.")


async def rec_003(request: FeatureRequest) -> FeatureResult:
    """[REC-003] Global Source 기반 추천.

    최신 외부 자료 중 관련성이 높은 것을 추천한다.
    """
    raise NotImplementedError("[REC-003] 기능 구현이 필요합니다.")


async def rec_004(request: FeatureRequest) -> FeatureResult:
    """[REC-004] 유사 콘텐츠 추천.

    현재 보고 있는 콘텐츠와 유사한 콘텐츠를 추천한다.
    """
    raise NotImplementedError("[REC-004] 기능 구현이 필요합니다.")


async def rec_005(request: FeatureRequest) -> FeatureResult:
    """[REC-005] 최신 콘텐츠 추천.

    최근 수집되거나 생성된 콘텐츠를 추천한다.
    """
    raise NotImplementedError("[REC-005] 기능 구현이 필요합니다.")


async def rec_006(request: FeatureRequest) -> FeatureResult:
    """[REC-006] 트렌드 콘텐츠 추천.

    사용자 관심사와 연결된 트렌드를 추천한다.
    """
    raise NotImplementedError("[REC-006] 기능 구현이 필요합니다.")


async def rec_007(request: FeatureRequest) -> FeatureResult:
    """[REC-007] 생성 콘텐츠 추천.

    다른 사용자의 공개 생성 콘텐츠를 추천한다.
    """
    raise NotImplementedError("[REC-007] 기능 구현이 필요합니다.")


async def rec_008(request: FeatureRequest) -> FeatureResult:
    """[REC-008] 북마크 기반 추천.

    사용자의 저장 콘텐츠를 기반으로 추천한다.
    """
    raise NotImplementedError("[REC-008] 기능 구현이 필요합니다.")
