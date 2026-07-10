"""기능 구현 모듈.

LLM-004, LLM-005 기능의 실제 구현 위치를 제공한다.
"""

from shared.contracts import FeatureRequest, FeatureResult


async def llm_004(request: FeatureRequest) -> FeatureResult:
    """[LLM-004] Tool Calling.

    Wiki 검색과 외부 도구 호출을 수행한다.
    """
    raise NotImplementedError("[LLM-004] 기능 구현이 필요합니다.")


async def llm_005(request: FeatureRequest) -> FeatureResult:
    """[LLM-005] Function Calling.

    정의된 내부 함수를 호출하고 결과를 활용한다.
    """
    raise NotImplementedError("[LLM-005] 기능 구현이 필요합니다.")
