"""기능 구현 모듈.

LLM-017, LLM-018 기능의 실제 구현 위치를 제공한다.
"""

from shared.contracts import FeatureRequest, FeatureResult


async def llm_017(request: FeatureRequest) -> FeatureResult:
    """[LLM-017] 안전성 검사.

    입력과 출력의 정책 위반 여부를 확인한다.
    """
    raise NotImplementedError("[LLM-017] 기능 구현이 필요합니다.")


async def llm_018(request: FeatureRequest) -> FeatureResult:
    """[LLM-018] Prompt Injection 방어.

    외부 문서의 명령을 시스템 지시와 분리한다.
    """
    raise NotImplementedError("[LLM-018] 기능 구현이 필요합니다.")
