"""기능 구현 모듈.

PWIKI-002, PWIKI-004, PWIKI-005 기능의 실제 구현 위치를 제공한다.
"""

from shared.contracts import FeatureRequest, FeatureResult


# MVP: agent-api-mvp-scope.md에서 구현 대상으로 지정된 기능입니다.
async def pwiki_002(request: FeatureRequest) -> FeatureResult:
    """[PWIKI-002] 개인 Wiki 문서 생성.

    사용자가 선택한 데이터를 Wiki 문서로 변환한다.
    """
    raise NotImplementedError("[PWIKI-002] 기능 구현이 필요합니다.")


async def pwiki_004(request: FeatureRequest) -> FeatureResult:
    """[PWIKI-004] 개인 Wiki 문서 수정.

    사용자 메모와 수정 내용을 Wiki 문서에 반영한다.
    """
    raise NotImplementedError("[PWIKI-004] 기능 구현이 필요합니다.")


# MVP: agent-api-mvp-scope.md에서 구현 대상으로 지정된 기능입니다.
async def pwiki_005(request: FeatureRequest) -> FeatureResult:
    """[PWIKI-005] 개인 Wiki 문서 삭제.

    사용자가 제거한 데이터를 Wiki 검색 대상에서 제외한다.
    """
    raise NotImplementedError("[PWIKI-005] 기능 구현이 필요합니다.")
