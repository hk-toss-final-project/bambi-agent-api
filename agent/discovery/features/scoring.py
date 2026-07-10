"""기능 구현 모듈.

DISC-005, DISC-006, DISC-007 기능의 실제 구현 위치를 제공한다.
"""

from shared.contracts import FeatureRequest, FeatureResult


async def disc_005(request: FeatureRequest) -> FeatureResult:
    """[DISC-005] 최신성 점수 계산.

    문서와 이벤트의 최신성 점수를 계산한다.
    """
    raise NotImplementedError("[DISC-005] 기능 구현이 필요합니다.")


async def disc_006(request: FeatureRequest) -> FeatureResult:
    """[DISC-006] 중요도 점수 계산.

    확산도와 관련성을 기반으로 중요도를 계산한다.
    """
    raise NotImplementedError("[DISC-006] 기능 구현이 필요합니다.")


async def disc_007(request: FeatureRequest) -> FeatureResult:
    """[DISC-007] 출처 다양성 평가.

    여러 Source가 동일 사실을 다루는지 평가한다.
    """
    raise NotImplementedError("[DISC-007] 기능 구현이 필요합니다.")
