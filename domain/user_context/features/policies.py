"""기능 구현 모듈.

CTX-006, CTX-007, CTX-008, CTX-009, CTX-010 기능의 실제 구현 위치를 제공한다.
"""

from shared.contracts import FeatureRequest, FeatureResult


async def ctx_006(request: FeatureRequest) -> FeatureResult:
    """[CTX-006] 플랜 정보 반영.

    무료·유료 플랜에 따른 Agent 정책을 연결한다.
    """
    raise NotImplementedError("[CTX-006] 기능 구현이 필요합니다.")


async def ctx_007(request: FeatureRequest) -> FeatureResult:
    """[CTX-007] 선호 언어 반영.

    사용자의 콘텐츠 생성 및 번역 언어를 반영한다.
    """
    raise NotImplementedError("[CTX-007] 기능 구현이 필요합니다.")


async def ctx_008(request: FeatureRequest) -> FeatureResult:
    """[CTX-008] 개인화 설정 반영.

    개인화 기능 사용 여부를 적용한다.
    """
    raise NotImplementedError("[CTX-008] 기능 구현이 필요합니다.")


async def ctx_009(request: FeatureRequest) -> FeatureResult:
    """[CTX-009] 차단 관심사 반영.

    사용자가 차단한 관심사를 검색과 생성에서 제외한다.
    """
    raise NotImplementedError("[CTX-009] 기능 구현이 필요합니다.")


async def ctx_010(request: FeatureRequest) -> FeatureResult:
    """[CTX-010] 차단 출처 반영.

    사용자가 차단한 Source를 추천과 생성에서 제외한다.
    """
    raise NotImplementedError("[CTX-010] 기능 구현이 필요합니다.")
