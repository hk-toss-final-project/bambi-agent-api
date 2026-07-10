"""기능 구현 모듈.

LLM-010, LLM-011 기능의 실제 구현 위치를 제공한다.
"""

from shared.contracts import FeatureRequest, FeatureResult


async def llm_010(request: FeatureRequest) -> FeatureResult:
    """[LLM-010] Context Builder.

    개인 Wiki와 Global Source Context를 구성한다.
    """
    raise NotImplementedError("[LLM-010] 기능 구현이 필요합니다.")


async def llm_011(request: FeatureRequest) -> FeatureResult:
    """[LLM-011] Citation Builder.

    생성 결과와 사용한 출처를 연결한다.
    """
    raise NotImplementedError("[LLM-011] 기능 구현이 필요합니다.")
