"""기능 구현 모듈.

PROMPT-005, PROMPT-006 기능의 실제 구현 위치를 제공한다.
"""

from shared.contracts import FeatureRequest, FeatureResult


async def prompt_005(request: FeatureRequest) -> FeatureResult:
    """[PROMPT-005] Prompt Version 생성.

    변경된 Prompt를 독립된 버전으로 저장한다.
    """
    raise NotImplementedError("[PROMPT-005] 기능 구현이 필요합니다.")


async def prompt_006(request: FeatureRequest) -> FeatureResult:
    """[PROMPT-006] Prompt Version 조회.

    Prompt의 전체 버전 이력을 조회한다.
    """
    raise NotImplementedError("[PROMPT-006] 기능 구현이 필요합니다.")
