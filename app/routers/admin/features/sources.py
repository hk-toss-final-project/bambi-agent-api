"""기능 구현 모듈.

ADMIN-006, ADMIN-007, ADMIN-008, ADMIN-009, ADMIN-010 기능의 실제 구현 위치를 제공한다.
"""

from shared.contracts import FeatureRequest, FeatureResult


async def admin_006(request: FeatureRequest) -> FeatureResult:
    """[ADMIN-006] Global Source 관리.

    외부 수집 Source와 설정을 관리한다.
    """
    raise NotImplementedError("[ADMIN-006] 기능 구현이 필요합니다.")


async def admin_007(request: FeatureRequest) -> FeatureResult:
    """[ADMIN-007] 수집 스케줄 관리.

    Source별 정기 수집 일정을 관리한다.
    """
    raise NotImplementedError("[ADMIN-007] 기능 구현이 필요합니다.")


async def admin_008(request: FeatureRequest) -> FeatureResult:
    """[ADMIN-008] 수집 작업 수동 실행.

    선택한 Source를 즉시 수집한다.
    """
    raise NotImplementedError("[ADMIN-008] 기능 구현이 필요합니다.")


async def admin_009(request: FeatureRequest) -> FeatureResult:
    """[ADMIN-009] 수집 이력 조회.

    Source별 수집 성공과 실패 이력을 조회한다.
    """
    raise NotImplementedError("[ADMIN-009] 기능 구현이 필요합니다.")


async def admin_010(request: FeatureRequest) -> FeatureResult:
    """[ADMIN-010] Global Source 문서 조회.

    수집된 외부 문서를 검수한다.
    """
    raise NotImplementedError("[ADMIN-010] 기능 구현이 필요합니다.")
