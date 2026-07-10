"""기능 구현 모듈.

NFR-013, NFR-017 기능의 실제 구현 위치를 제공한다.
"""

from shared.contracts import FeatureRequest, FeatureResult


async def nfr_013(request: FeatureRequest) -> FeatureResult:
    """[NFR-013] Graceful Degradation.

    일부 Provider 장애 시 핵심 기능을 제한적으로 제공한다.
    """
    raise NotImplementedError("[NFR-013] 기능 구현이 필요합니다.")


async def nfr_017(request: FeatureRequest) -> FeatureResult:
    """[NFR-017] Provider 장애 대응.

    외부 API와 모델 장애 시 Fallback을 적용한다.
    """
    raise NotImplementedError("[NFR-017] 기능 구현이 필요합니다.")
