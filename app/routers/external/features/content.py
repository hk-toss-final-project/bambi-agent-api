"""기능 구현 모듈.

EXT-001, EXT-002, EXT-003, EXT-006, EXT-007 기능의 실제 구현 위치를 제공한다.
"""

from shared.contracts import FeatureRequest, FeatureResult


async def ext_001(request: FeatureRequest) -> FeatureResult:
    """[EXT-001] 외부 요약 API.

    외부 시스템에 문서와 URL 요약 기능을 제공한다.
    """
    raise NotImplementedError("[EXT-001] 기능 구현이 필요합니다.")


async def ext_002(request: FeatureRequest) -> FeatureResult:
    """[EXT-002] 외부 번역 API.

    외부 시스템에 번역 기능을 제공한다.
    """
    raise NotImplementedError("[EXT-002] 기능 구현이 필요합니다.")


async def ext_003(request: FeatureRequest) -> FeatureResult:
    """[EXT-003] 외부 콘텐츠 생성 API.

    외부 시스템에서 콘텐츠 생성을 요청할 수 있게 한다.
    """
    raise NotImplementedError("[EXT-003] 기능 구현이 필요합니다.")


async def ext_006(request: FeatureRequest) -> FeatureResult:
    """[EXT-006] 외부 추천 API.

    사용자 컨텍스트 기반 추천 기능을 제공한다.
    """
    raise NotImplementedError("[EXT-006] 기능 구현이 필요합니다.")


async def ext_007(request: FeatureRequest) -> FeatureResult:
    """[EXT-007] 외부 이미지 생성 API.

    외부 시스템에 이미지 생성 기능을 제공한다.
    """
    raise NotImplementedError("[EXT-007] 기능 구현이 필요합니다.")
