"""기능 구현 모듈.

BAMBI-021 기능의 실제 구현 위치를 제공한다.
"""

from shared.contracts import FeatureRequest, FeatureResult


# MVP: agent-api-mvp-scope.md에서 구현 대상으로 지정된 기능입니다.
async def bambi_021(request: FeatureRequest) -> FeatureResult:
    """[BAMBI-021] 자동 Wiki 편입 금지.

    생성된 콘텐츠를 사용자 선택 없이 개인 Wiki에 넣지 않는다.
    """
    raise NotImplementedError("[BAMBI-021] 기능 구현이 필요합니다.")
