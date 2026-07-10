"""기능 구현 모듈.

OBJ-007, OBJ-008, OBJ-009, OBJ-010 기능의 실제 구현 위치를 제공한다.
"""

from shared.contracts import FeatureRequest, FeatureResult


async def obj_007(request: FeatureRequest) -> FeatureResult:
    """[OBJ-007] 생성 이미지 저장.

    콘텐츠용 생성 이미지를 저장한다.
    """
    raise NotImplementedError("[OBJ-007] 기능 구현이 필요합니다.")


async def obj_008(request: FeatureRequest) -> FeatureResult:
    """[OBJ-008] 썸네일 저장.

    피드 카드용 썸네일을 저장한다.
    """
    raise NotImplementedError("[OBJ-008] 기능 구현이 필요합니다.")


async def obj_009(request: FeatureRequest) -> FeatureResult:
    """[OBJ-009] 인포그래픽 저장.

    생성된 인포그래픽 파일을 저장한다.
    """
    raise NotImplementedError("[OBJ-009] 기능 구현이 필요합니다.")


async def obj_010(request: FeatureRequest) -> FeatureResult:
    """[OBJ-010] 차트 이미지 저장.

    생성된 차트 파일을 저장한다.
    """
    raise NotImplementedError("[OBJ-010] 기능 구현이 필요합니다.")
