"""기능 구현 모듈.

OBJ-013, OBJ-014 기능의 실제 구현 위치를 제공한다.
"""

from shared.contracts import FeatureRequest, FeatureResult


async def obj_013(request: FeatureRequest) -> FeatureResult:
    """[OBJ-013] Object 보존 기간 관리.

    파일 유형별 보존 기간을 적용한다.
    """
    raise NotImplementedError("[OBJ-013] 기능 구현이 필요합니다.")


async def obj_014(request: FeatureRequest) -> FeatureResult:
    """[OBJ-014] Object 삭제 처리.

    삭제 요청과 보존 정책에 따라 파일을 제거한다.
    """
    raise NotImplementedError("[OBJ-014] 기능 구현이 필요합니다.")
