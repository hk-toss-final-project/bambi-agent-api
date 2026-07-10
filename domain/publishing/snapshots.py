"""기능 구현 모듈.

PUB-001 기능의 실제 구현 위치를 제공한다.
"""

from shared.contracts import FeatureRequest, FeatureResult


async def pub_001(request: FeatureRequest) -> FeatureResult:
    """[PUB-001] 발행용 Snapshot 생성.

    service-db에 저장할 콘텐츠 형식을 생성한다.
    """
    raise NotImplementedError("[PUB-001] 기능 구현이 필요합니다.")
