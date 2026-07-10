"""기능 구현 모듈.

SW-004, SW-005, SW-006, SW-013 기능의 실제 구현 위치를 제공한다.
"""

from shared.contracts import FeatureRequest, FeatureResult


# MVP: agent-api-mvp-scope.md에서 구현 대상으로 지정된 기능입니다.
async def sw_004(request: FeatureRequest) -> FeatureResult:
    """[SW-004] Publish Snapshot 조회.

    Agent API에서 서비스 저장용 콘텐츠를 조회한다.
    """
    raise NotImplementedError("[SW-004] 기능 구현이 필요합니다.")


async def sw_005(request: FeatureRequest) -> FeatureResult:
    """[SW-005] 발행 가능 상태 검증.

    콘텐츠가 실제 발행 가능한 상태인지 확인한다.
    """
    raise NotImplementedError("[SW-005] 기능 구현이 필요합니다.")


async def sw_006(request: FeatureRequest) -> FeatureResult:
    """[SW-006] 콘텐츠 Version 검증.

    오래된 콘텐츠 버전이 반영되지 않도록 확인한다.
    """
    raise NotImplementedError("[SW-006] 기능 구현이 필요합니다.")


async def sw_013(request: FeatureRequest) -> FeatureResult:
    """[SW-013] 콘텐츠 무결성 검증.

    Snapshot의 Hash와 버전을 확인한다.
    """
    raise NotImplementedError("[SW-013] 기능 구현이 필요합니다.")
