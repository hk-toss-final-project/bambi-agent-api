"""기능 구현 모듈.

SVC-002, SVC-003, SVC-004, SVC-005, SVC-006, SVC-007 기능의 실제 구현 위치를 제공한다.
"""

from shared.contracts import FeatureRequest, FeatureResult


# MVP: agent-api-mvp-scope.md에서 구현 대상으로 지정된 기능입니다.
async def svc_002(request: FeatureRequest) -> FeatureResult:
    """[SVC-002] 웹 클리핑 처리 요청.

    클리핑 데이터를 개인 Wiki 처리 작업으로 전달한다.
    """
    raise NotImplementedError("[SVC-002] 기능 구현이 필요합니다.")


# MVP: agent-api-mvp-scope.md에서 구현 대상으로 지정된 기능입니다.
async def svc_003(request: FeatureRequest) -> FeatureResult:
    """[SVC-003] URL 처리 요청.

    입력된 URL을 개인 Wiki 처리 작업으로 전달한다.
    """
    raise NotImplementedError("[SVC-003] 기능 구현이 필요합니다.")


# MVP: agent-api-mvp-scope.md에서 구현 대상으로 지정된 기능입니다.
async def svc_004(request: FeatureRequest) -> FeatureResult:
    """[SVC-004] 위키마킹 처리 요청.

    사용자가 선택한 콘텐츠의 Wiki 편입을 요청한다.
    """
    raise NotImplementedError("[SVC-004] 기능 구현이 필요합니다.")


async def svc_005(request: FeatureRequest) -> FeatureResult:
    """[SVC-005] 콘텐츠 상호작용 전달.

    콘텐츠와의 대화와 수정 결과를 전달한다.
    """
    raise NotImplementedError("[SVC-005] 기능 구현이 필요합니다.")


async def svc_006(request: FeatureRequest) -> FeatureResult:
    """[SVC-006] 사용자 피드백 전달.

    좋아요, 숨김, 신고 등의 신호를 전달한다.
    """
    raise NotImplementedError("[SVC-006] 기능 구현이 필요합니다.")


async def svc_007(request: FeatureRequest) -> FeatureResult:
    """[SVC-007] 개인 Wiki 재구성 요청.

    특정 사용자의 Wiki 재구성을 요청한다.
    """
    raise NotImplementedError("[SVC-007] 기능 구현이 필요합니다.")
