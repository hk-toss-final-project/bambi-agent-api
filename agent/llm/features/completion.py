"""기능 구현 모듈.

LLM-001, LLM-002, LLM-003 기능의 실제 구현 위치를 제공한다.
"""

from shared.contracts import FeatureRequest, FeatureResult


async def llm_001(request: FeatureRequest) -> FeatureResult:
    """[LLM-001] Text Completion.

    일반 텍스트 생성 요청을 처리한다.
    """
    raise NotImplementedError("[LLM-001] 기능 구현이 필요합니다.")


async def llm_002(request: FeatureRequest) -> FeatureResult:
    """[LLM-002] Chat Completion.

    대화형 생성 요청을 처리한다.
    """
    raise NotImplementedError("[LLM-002] 기능 구현이 필요합니다.")


async def llm_003(request: FeatureRequest) -> FeatureResult:
    """[LLM-003] Structured Output.

    정해진 Schema 형식으로 결과를 생성한다.
    """
    raise NotImplementedError("[LLM-003] 기능 구현이 필요합니다.")
