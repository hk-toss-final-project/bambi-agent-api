"""기능 구현 모듈.

DISC-003, DISC-004 기능의 실제 구현 위치를 제공한다.
"""

from shared.contracts import FeatureRequest, FeatureResult


async def disc_003(request: FeatureRequest) -> FeatureResult:
    """[DISC-003] 유사 문서 클러스터링.

    같은 사건이나 주제를 다루는 문서를 그룹화한다.
    """
    raise NotImplementedError("[DISC-003] 기능 구현이 필요합니다.")


async def disc_004(request: FeatureRequest) -> FeatureResult:
    """[DISC-004] 뉴스 이벤트 클러스터링.

    관련 뉴스들을 하나의 이벤트 단위로 구성한다.
    """
    raise NotImplementedError("[DISC-004] 기능 구현이 필요합니다.")
