"""기능 구현 모듈.

NFR-003, NFR-004 기능의 실제 구현 위치를 제공한다.
"""

from shared.contracts import FeatureRequest, FeatureResult


async def nfr_003(request: FeatureRequest) -> FeatureResult:
    """[NFR-003] Event Schema Versioning.

    이벤트 구조 변경을 버전으로 관리한다.
    """
    raise NotImplementedError("[NFR-003] 기능 구현이 필요합니다.")


async def nfr_004(request: FeatureRequest) -> FeatureResult:
    """[NFR-004] API Schema Versioning.

    API 구조 변경을 버전으로 관리한다.
    """
    raise NotImplementedError("[NFR-004] 기능 구현이 필요합니다.")
