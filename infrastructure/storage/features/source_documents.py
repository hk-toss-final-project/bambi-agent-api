"""기능 구현 모듈.

OBJ-001, OBJ-002, OBJ-003, OBJ-004 기능의 실제 구현 위치를 제공한다.
"""

from shared.contracts import FeatureRequest, FeatureResult


async def obj_001(request: FeatureRequest) -> FeatureResult:
    """[OBJ-001] 원본 HTML 저장.

    수집 또는 클리핑한 HTML 원문을 저장한다.
    """
    raise NotImplementedError("[OBJ-001] 기능 구현이 필요합니다.")


async def obj_002(request: FeatureRequest) -> FeatureResult:
    """[OBJ-002] PDF 저장.

    논문과 공시 등의 PDF 원문을 저장한다.
    """
    raise NotImplementedError("[OBJ-002] 기능 구현이 필요합니다.")


async def obj_003(request: FeatureRequest) -> FeatureResult:
    """[OBJ-003] 외부 API 원본 응답 저장.

    대용량 외부 API 응답을 저장한다.
    """
    raise NotImplementedError("[OBJ-003] 기능 구현이 필요합니다.")


async def obj_004(request: FeatureRequest) -> FeatureResult:
    """[OBJ-004] 대용량 본문 저장.

    DB에 적합하지 않은 긴 텍스트를 저장한다.
    """
    raise NotImplementedError("[OBJ-004] 기능 구현이 필요합니다.")
