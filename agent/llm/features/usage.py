"""기능 구현 모듈.

LLM-015, LLM-016 기능의 실제 구현 위치를 제공한다.
"""

from shared.contracts import FeatureRequest, FeatureResult


async def llm_015(request: FeatureRequest) -> FeatureResult:
    """[LLM-015] 사용량 기록.

    모델 호출량과 Token 사용량을 기록한다.
    """
    raise NotImplementedError("[LLM-015] 기능 구현이 필요합니다.")


async def llm_016(request: FeatureRequest) -> FeatureResult:
    """[LLM-016] 비용 기록.

    Provider와 작업별 예상 비용을 기록한다.
    """
    raise NotImplementedError("[LLM-016] 기능 구현이 필요합니다.")
