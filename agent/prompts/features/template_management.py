"""Prompt Template 관리 기능 구현 모듈.

PROMPT-001, PROMPT-002, PROMPT-003, PROMPT-004 기능의 실제 구현 위치를 제공한다.
"""

from shared.contracts import FeatureRequest, FeatureResult


async def prompt_001(request: FeatureRequest) -> FeatureResult:
    """[PROMPT-001] Prompt Template 생성.

    Agent 기능별 Prompt Template을 생성한다.
    """
    raise NotImplementedError("[PROMPT-001] 기능 구현이 필요합니다.")


async def prompt_002(request: FeatureRequest) -> FeatureResult:
    """[PROMPT-002] Prompt Template 조회.

    등록된 Prompt Template을 조회한다.
    """
    raise NotImplementedError("[PROMPT-002] 기능 구현이 필요합니다.")


async def prompt_003(request: FeatureRequest) -> FeatureResult:
    """[PROMPT-003] Prompt Template 수정.

    Prompt 내용을 새 버전으로 수정한다.
    """
    raise NotImplementedError("[PROMPT-003] 기능 구현이 필요합니다.")


async def prompt_004(request: FeatureRequest) -> FeatureResult:
    """[PROMPT-004] Prompt Template 삭제.

    사용하지 않는 Prompt Template을 비활성화한다.
    """
    raise NotImplementedError("[PROMPT-004] 기능 구현이 필요합니다.")
