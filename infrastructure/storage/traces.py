"""기능 구현 모듈.

OBJ-006 기능의 실제 구현 위치를 제공한다.
"""

from shared.contracts import FeatureRequest, FeatureResult


async def obj_006(request: FeatureRequest) -> FeatureResult:
    """[OBJ-006] LLM Trace 저장.

    전체 Prompt, Completion, Tool Trace를 저장한다.
    """
    raise NotImplementedError("[OBJ-006] 기능 구현이 필요합니다.")
