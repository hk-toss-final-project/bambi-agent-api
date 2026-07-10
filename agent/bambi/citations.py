"""기능 구현 모듈.

BAMBI-011 기능의 실제 구현 위치를 제공한다.
"""

from shared.contracts import FeatureRequest, FeatureResult


# MVP: agent-api-mvp-scope.md에서 구현 대상으로 지정된 기능입니다.
async def bambi_011(request: FeatureRequest) -> FeatureResult:
    """[BAMBI-011] 콘텐츠 Citation 생성.

    본문 주장과 참조한 자료를 연결한다.
    """
    raise NotImplementedError("[BAMBI-011] 기능 구현이 필요합니다.")
