"""기능 구현 모듈.

OBJ-012 기능의 실제 구현 위치를 제공한다.
"""

from shared.contracts import FeatureRequest, FeatureResult


async def obj_012(request: FeatureRequest) -> FeatureResult:
    """[OBJ-012] Object Metadata 관리.

    크기, 형식, Checksum 등의 정보를 관리한다.
    """
    raise NotImplementedError("[OBJ-012] 기능 구현이 필요합니다.")
