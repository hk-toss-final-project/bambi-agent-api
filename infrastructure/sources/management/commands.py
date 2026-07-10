"""기능 구현 모듈.

GS-001, GS-003, GS-004 기능의 실제 구현 위치를 제공한다.
"""

from shared.contracts import FeatureRequest, FeatureResult


async def gs_001(request: FeatureRequest) -> FeatureResult:
    """[GS-001] Global Source 등록.

    외부 수집 Source를 등록한다.
    """
    raise NotImplementedError("[GS-001] 기능 구현이 필요합니다.")


async def gs_003(request: FeatureRequest) -> FeatureResult:
    """[GS-003] Global Source 수정.

    Source의 수집 설정을 변경한다.
    """
    raise NotImplementedError("[GS-003] 기능 구현이 필요합니다.")


async def gs_004(request: FeatureRequest) -> FeatureResult:
    """[GS-004] Global Source 삭제.

    사용하지 않는 Source를 제거한다.
    """
    raise NotImplementedError("[GS-004] 기능 구현이 필요합니다.")
