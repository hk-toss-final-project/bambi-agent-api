"""기능 구현 모듈.

PROMPT-008, PROMPT-011 기능의 실제 구현 위치를 제공한다.
"""

from shared.contracts import FeatureRequest, FeatureResult


async def prompt_008(request: FeatureRequest) -> FeatureResult:
    """[PROMPT-008] Prompt 테스트.

    샘플 입력으로 Prompt 결과를 테스트한다.
    """
    raise NotImplementedError("[PROMPT-008] 기능 구현이 필요합니다.")


async def prompt_011(request: FeatureRequest) -> FeatureResult:
    """[PROMPT-011] Prompt A/B Test.

    여러 Prompt의 품질과 비용을 비교한다.
    """
    raise NotImplementedError("[PROMPT-011] 기능 구현이 필요합니다.")
