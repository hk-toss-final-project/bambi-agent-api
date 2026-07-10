"""기능 구현 모듈.

BAMBI-003, BAMBI-012 기능의 실제 구현 위치를 제공한다.
"""

from shared.contracts import FeatureRequest, FeatureResult


async def bambi_003(request: FeatureRequest) -> FeatureResult:
    """[BAMBI-003] 사용자 컨텍스트 조회.

    생성에 필요한 사용자 설정과 플랜을 조회한다.
    """
    raise NotImplementedError("[BAMBI-003] 기능 구현이 필요합니다.")


# MVP: agent-api-mvp-scope.md에서 구현 대상으로 지정된 기능입니다.
async def bambi_012(request: FeatureRequest) -> FeatureResult:
    """[BAMBI-012] 사용자 개인화 적용.

    관심사, 언어, 비선호 설정을 반영한다.
    """
    raise NotImplementedError("[BAMBI-012] 기능 구현이 필요합니다.")
