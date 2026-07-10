"""기능 구현 모듈.

BAMBI-020 기능의 실제 구현 위치를 제공한다.
"""

from shared.contracts import FeatureRequest, FeatureResult


# MVP: agent-api-mvp-scope.md에서 구현 대상으로 지정된 기능입니다.
async def bambi_020(request: FeatureRequest) -> FeatureResult:
    """[BAMBI-020] 콘텐츠 완료 이벤트.

    생성 완료 사실을 Integration Event로 발행한다.
    """
    raise NotImplementedError("[BAMBI-020] 기능 구현이 필요합니다.")
