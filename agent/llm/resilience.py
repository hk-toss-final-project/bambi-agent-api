"""기능 구현 모듈.

LLM-013, LLM-014 기능의 실제 구현 위치를 제공한다.
"""

from shared.contracts import FeatureRequest, FeatureResult


async def llm_013(request: FeatureRequest) -> FeatureResult:
    """[LLM-013] 호출 Retry.

    일시적인 Provider 오류를 재시도한다.
    """
    raise NotImplementedError("[LLM-013] 기능 구현이 필요합니다.")


async def llm_014(request: FeatureRequest) -> FeatureResult:
    """[LLM-014] 호출 Timeout.

    LLM 요청의 최대 실행 시간을 제한한다.
    """
    raise NotImplementedError("[LLM-014] 기능 구현이 필요합니다.")
