"""기능 구현 모듈.

BAMBI-007, BAMBI-008, BAMBI-009, BAMBI-010 기능의 실제 구현 위치를 제공한다.
"""

from shared.contracts import FeatureRequest, FeatureResult


async def bambi_007(request: FeatureRequest) -> FeatureResult:
    """[BAMBI-007] 콘텐츠 제목 생성.

    콘텐츠 목적에 맞는 제목을 생성한다.
    """
    raise NotImplementedError("[BAMBI-007] 기능 구현이 필요합니다.")


# MVP: agent-api-mvp-scope.md에서 구현 대상으로 지정된 기능입니다.
async def bambi_008(request: FeatureRequest) -> FeatureResult:
    """[BAMBI-008] 콘텐츠 요약 생성.

    피드와 미리보기에 사용할 요약을 생성한다.
    """
    raise NotImplementedError("[BAMBI-008] 기능 구현이 필요합니다.")


# MVP: agent-api-mvp-scope.md에서 구현 대상으로 지정된 기능입니다.
async def bambi_009(request: FeatureRequest) -> FeatureResult:
    """[BAMBI-009] 콘텐츠 본문 생성.

    플랜과 유형에 맞는 본문을 생성한다.
    """
    raise NotImplementedError("[BAMBI-009] 기능 구현이 필요합니다.")


async def bambi_010(request: FeatureRequest) -> FeatureResult:
    """[BAMBI-010] 콘텐츠 태그 생성.

    콘텐츠 검색과 추천에 사용할 태그를 생성한다.
    """
    raise NotImplementedError("[BAMBI-010] 기능 구현이 필요합니다.")
