"""기능 구현 모듈.

ADMIN-014, ADMIN-015, ADMIN-016, ADMIN-017 기능의 실제 구현 위치를 제공한다.
"""

from shared.contracts import FeatureRequest, FeatureResult


async def admin_014(request: FeatureRequest) -> FeatureResult:
    """[ADMIN-014] 생성 콘텐츠 후보 조회.

    발행 전 생성 콘텐츠를 검수한다.
    """
    raise NotImplementedError("[ADMIN-014] 기능 구현이 필요합니다.")


async def admin_015(request: FeatureRequest) -> FeatureResult:
    """[ADMIN-015] 콘텐츠 재생성.

    선택한 콘텐츠를 새로운 설정으로 재생성한다.
    """
    raise NotImplementedError("[ADMIN-015] 기능 구현이 필요합니다.")


async def admin_016(request: FeatureRequest) -> FeatureResult:
    """[ADMIN-016] 콘텐츠 품질 평가 조회.

    품질 점수와 평가 결과를 조회한다.
    """
    raise NotImplementedError("[ADMIN-016] 기능 구현이 필요합니다.")


async def admin_017(request: FeatureRequest) -> FeatureResult:
    """[ADMIN-017] 콘텐츠 안전성 평가 조회.

    안전성 검사 결과를 조회한다.
    """
    raise NotImplementedError("[ADMIN-017] 기능 구현이 필요합니다.")
