"""기능 구현 모듈.

NFR-018, NFR-019 기능의 실제 구현 위치를 제공한다.
"""

from shared.contracts import FeatureRequest, FeatureResult


async def nfr_018(request: FeatureRequest) -> FeatureResult:
    """[NFR-018] 데이터 무결성.

    문서, Chunk, Embedding 간 관계를 일관되게 유지한다.
    """
    raise NotImplementedError("[NFR-018] 기능 구현이 필요합니다.")


async def nfr_019(request: FeatureRequest) -> FeatureResult:
    """[NFR-019] 콘텐츠 무결성.

    발행본과 Agent 생성본의 버전과 Hash를 검증한다.
    """
    raise NotImplementedError("[NFR-019] 기능 구현이 필요합니다.")
