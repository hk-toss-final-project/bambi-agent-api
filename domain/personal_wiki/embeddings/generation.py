"""기능 구현 모듈.

PWE-004, PWE-006, PWE-007 기능의 실제 구현 위치를 제공한다.
"""

from shared.contracts import FeatureRequest, FeatureResult


# MVP: agent-api-mvp-scope.md에서 구현 대상으로 지정된 기능입니다.
async def pwe_004(request: FeatureRequest) -> FeatureResult:
    """[PWE-004] Embedding 생성.

    개인 Wiki Chunk의 Vector를 생성한다.
    """
    raise NotImplementedError("[PWE-004] 기능 구현이 필요합니다.")


async def pwe_006(request: FeatureRequest) -> FeatureResult:
    """[PWE-006] Embedding 갱신.

    문서 변경 시 관련 Embedding을 갱신한다.
    """
    raise NotImplementedError("[PWE-006] 기능 구현이 필요합니다.")


async def pwe_007(request: FeatureRequest) -> FeatureResult:
    """[PWE-007] Embedding 재생성.

    모델 또는 Chunk 정책 변경 시 재생성한다.
    """
    raise NotImplementedError("[PWE-007] 기능 구현이 필요합니다.")
