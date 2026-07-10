"""기능 구현 모듈.

IMG-001, IMG-002, IMG-003, IMG-004, IMG-005, IMG-006 기능의 실제 구현 위치를 제공한다.
"""

from shared.contracts import FeatureRequest, FeatureResult


async def img_001(request: FeatureRequest) -> FeatureResult:
    """[IMG-001] 콘텐츠 이미지 생성.

    콘텐츠에 사용할 대표 이미지를 생성한다.
    """
    raise NotImplementedError("[IMG-001] 기능 구현이 필요합니다.")


async def img_002(request: FeatureRequest) -> FeatureResult:
    """[IMG-002] 썸네일 생성.

    피드 카드용 썸네일을 생성한다.
    """
    raise NotImplementedError("[IMG-002] 기능 구현이 필요합니다.")


async def img_003(request: FeatureRequest) -> FeatureResult:
    """[IMG-003] 콘텐츠 삽화 생성.

    본문 이해를 돕는 삽화를 생성한다.
    """
    raise NotImplementedError("[IMG-003] 기능 구현이 필요합니다.")


async def img_004(request: FeatureRequest) -> FeatureResult:
    """[IMG-004] 인포그래픽 생성.

    핵심 정보를 시각 자료로 구성한다.
    """
    raise NotImplementedError("[IMG-004] 기능 구현이 필요합니다.")


async def img_005(request: FeatureRequest) -> FeatureResult:
    """[IMG-005] 차트 이미지 생성.

    구조화된 데이터를 차트로 생성한다.
    """
    raise NotImplementedError("[IMG-005] 기능 구현이 필요합니다.")


async def img_006(request: FeatureRequest) -> FeatureResult:
    """[IMG-006] 다이어그램 생성.

    개념과 관계를 도식화한다.
    """
    raise NotImplementedError("[IMG-006] 기능 구현이 필요합니다.")
