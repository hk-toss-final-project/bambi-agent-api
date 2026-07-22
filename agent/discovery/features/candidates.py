"""기능 구현 모듈.

DISC-009, DISC-010, DISC-011, DISC-012 기능의 실제 구현 위치를 제공한다.
"""

from shared.contracts import FeatureRequest, FeatureResult


async def disc_009(request: FeatureRequest) -> FeatureResult:
    """[DISC-009] 콘텐츠 생성 후보 생성.

    리포트 생성기가 사용할 최신 자료 후보를 생성한다.
    """
    raise NotImplementedError("[DISC-009] 기능 구현이 필요합니다.")


async def disc_010(request: FeatureRequest) -> FeatureResult:
    """[DISC-010] 추천 후보 생성.

    사용자에게 추천할 외부 콘텐츠 후보를 생성한다.
    """
    raise NotImplementedError("[DISC-010] 기능 구현이 필요합니다.")


async def disc_011(request: FeatureRequest) -> FeatureResult:
    """[DISC-011] 중복 후보 제거.

    이미 처리했거나 유사한 후보를 제거한다.
    """
    raise NotImplementedError("[DISC-011] 기능 구현이 필요합니다.")


async def disc_012(request: FeatureRequest) -> FeatureResult:
    """[DISC-012] 트렌드 후보 저장.

    탐지된 트렌드와 관련 문서를 저장한다.
    """
    raise NotImplementedError("[DISC-012] 기능 구현이 필요합니다.")
