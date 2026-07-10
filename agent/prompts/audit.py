"""기능 구현 모듈.

PROMPT-010 기능의 실제 구현 위치를 제공한다.
"""

from shared.contracts import FeatureRequest, FeatureResult


async def prompt_010(request: FeatureRequest) -> FeatureResult:
    """[PROMPT-010] Prompt 변경 이력.

    변경자와 변경 사유를 기록한다.
    """
    raise NotImplementedError("[PROMPT-010] 기능 구현이 필요합니다.")
