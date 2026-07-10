"""기능 구현 모듈.

PROMPT-007, PROMPT-009 기능의 실제 구현 위치를 제공한다.
"""

from shared.contracts import FeatureRequest, FeatureResult


async def prompt_007(request: FeatureRequest) -> FeatureResult:
    """[PROMPT-007] 활성 Prompt 전환.

    운영에 사용할 Prompt 버전을 선택한다.
    """
    raise NotImplementedError("[PROMPT-007] 기능 구현이 필요합니다.")


async def prompt_009(request: FeatureRequest) -> FeatureResult:
    """[PROMPT-009] Prompt 롤백.

    이전 Prompt 버전으로 되돌린다.
    """
    raise NotImplementedError("[PROMPT-009] 기능 구현이 필요합니다.")
