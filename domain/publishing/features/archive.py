"""기능 구현 모듈.

PUB-008, PUB-009 기능의 실제 구현 위치를 제공한다.
"""

from shared.contracts import FeatureRequest, FeatureResult


async def pub_008(request: FeatureRequest) -> FeatureResult:
    """[PUB-008] 콘텐츠 Archive.

    더 이상 노출하지 않는 콘텐츠를 보관 상태로 변경한다.
    """
    raise NotImplementedError("[PUB-008] 기능 구현이 필요합니다.")


async def pub_009(request: FeatureRequest) -> FeatureResult:
    """[PUB-009] 콘텐츠 Superseded.

    새 버전으로 대체된 콘텐츠 상태를 관리한다.
    """
    raise NotImplementedError("[PUB-009] 기능 구현이 필요합니다.")
