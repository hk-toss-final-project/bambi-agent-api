"""기능 구현 모듈.

LLM-006, LLM-007, LLM-008, LLM-019 기능의 실제 구현 위치를 제공한다.
"""

from shared.contracts import FeatureRequest, FeatureResult


async def llm_006(request: FeatureRequest) -> FeatureResult:
    """[LLM-006] 모델 라우팅.

    작업 성격과 플랜에 맞는 모델을 선택한다.
    """
    raise NotImplementedError("[LLM-006] 기능 구현이 필요합니다.")


async def llm_007(request: FeatureRequest) -> FeatureResult:
    """[LLM-007] Provider 라우팅.

    사용 가능한 LLM Provider를 선택한다.
    """
    raise NotImplementedError("[LLM-007] 기능 구현이 필요합니다.")


async def llm_008(request: FeatureRequest) -> FeatureResult:
    """[LLM-008] Fallback 모델.

    주 모델 실패 시 대체 모델을 사용한다.
    """
    raise NotImplementedError("[LLM-008] 기능 구현이 필요합니다.")


async def llm_019(request: FeatureRequest) -> FeatureResult:
    """[LLM-019] Provider 추상화.

    Provider 교체가 가능하도록 공통 인터페이스를 제공한다.
    """
    raise NotImplementedError("[LLM-019] 기능 구현이 필요합니다.")
