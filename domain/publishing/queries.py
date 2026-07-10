"""기능 구현 모듈.

PUB-002, PUB-003 기능의 실제 구현 위치를 제공한다.
"""

from shared.contracts import FeatureRequest, FeatureResult


async def pub_002(request: FeatureRequest) -> FeatureResult:
    """[PUB-002] 생성 콘텐츠 조회.

    Agent DB의 생성 결과를 조회한다.
    """
    raise NotImplementedError("[PUB-002] 기능 구현이 필요합니다.")


async def pub_003(request: FeatureRequest) -> FeatureResult:
    """[PUB-003] 생성 콘텐츠 Version 조회.

    특정 버전의 생성 결과를 조회한다.
    """
    raise NotImplementedError("[PUB-003] 기능 구현이 필요합니다.")
