"""기능 구현 모듈.

PWE-005, PWE-010 기능의 실제 구현 위치를 제공한다.
"""

from shared.contracts import FeatureRequest, FeatureResult


# MVP: agent-api-mvp-scope.md에서 구현 대상으로 지정된 기능입니다.
async def pwe_005(request: FeatureRequest) -> FeatureResult:
    """[PWE-005] Embedding 저장.

    사용자별 Vector 검색 저장소에 Embedding을 저장한다.
    """
    raise NotImplementedError("[PWE-005] 기능 구현이 필요합니다.")


async def pwe_010(request: FeatureRequest) -> FeatureResult:
    """[PWE-010] 삭제 Vector 반영.

    문서 삭제 시 관련 Vector도 검색 대상에서 제거한다.
    """
    raise NotImplementedError("[PWE-010] 기능 구현이 필요합니다.")
