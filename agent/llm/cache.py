"""기능 구현 모듈.

LLM-012 기능의 실제 구현 위치를 제공한다.
"""

from shared.contracts import FeatureRequest, FeatureResult


async def llm_012(request: FeatureRequest) -> FeatureResult:
    """[LLM-012] 응답 캐싱.

    재사용 가능한 LLM 결과를 캐시한다.
    """
    raise NotImplementedError("[LLM-012] 기능 구현이 필요합니다.")
