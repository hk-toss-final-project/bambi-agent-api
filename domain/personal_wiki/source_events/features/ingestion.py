"""기능 구현 모듈.

WSE-001, WSE-002, WSE-003, WSE-004, WSE-005, WSE-006, WSE-007, WSE-008 기능의 실제 구현 위치를 제공한다.
"""

from shared.contracts import FeatureRequest, FeatureResult


# MVP: agent-api-mvp-scope.md에서 구현 대상으로 지정된 기능입니다.
async def wse_001(request: FeatureRequest) -> FeatureResult:
    """[WSE-001] 웹 클리핑 이벤트 수신.

    사용자가 클리핑한 데이터를 개인 Wiki 반영 후보로 수신한다.
    """
    raise NotImplementedError("[WSE-001] 기능 구현이 필요합니다.")


async def wse_002(request: FeatureRequest) -> FeatureResult:
    """[WSE-002] URL 입력 이벤트 수신.

    사용자가 직접 입력한 URL을 개인 Wiki 반영 후보로 수신한다.
    """
    raise NotImplementedError("[WSE-002] 기능 구현이 필요합니다.")


async def wse_003(request: FeatureRequest) -> FeatureResult:
    """[WSE-003] 콘텐츠 위키마킹 이벤트 수신.

    선택한 생성 콘텐츠를 개인 Wiki 반영 후보로 수신한다.
    """
    raise NotImplementedError("[WSE-003] 기능 구현이 필요합니다.")


async def wse_004(request: FeatureRequest) -> FeatureResult:
    """[WSE-004] 콘텐츠 저장 이벤트 수신.

    사용자가 저장한 콘텐츠를 정책에 따라 처리한다.
    """
    raise NotImplementedError("[WSE-004] 기능 구현이 필요합니다.")


async def wse_005(request: FeatureRequest) -> FeatureResult:
    """[WSE-005] 사용자 메모 이벤트 수신.

    문서나 콘텐츠에 작성한 메모를 수신한다.
    """
    raise NotImplementedError("[WSE-005] 기능 구현이 필요합니다.")


async def wse_006(request: FeatureRequest) -> FeatureResult:
    """[WSE-006] 생성 콘텐츠 수정 이벤트 수신.

    사용자가 수정한 생성 콘텐츠를 수신한다.
    """
    raise NotImplementedError("[WSE-006] 기능 구현이 필요합니다.")


async def wse_007(request: FeatureRequest) -> FeatureResult:
    """[WSE-007] 콘텐츠 대화 이벤트 수신.

    콘텐츠와의 의미 있는 대화 결과를 수신한다.
    """
    raise NotImplementedError("[WSE-007] 기능 구현이 필요합니다.")


async def wse_008(request: FeatureRequest) -> FeatureResult:
    """[WSE-008] 사용자 피드백 이벤트 수신.

    좋아요, 숨김, 신고 등 사용자 반응을 수신한다.
    """
    raise NotImplementedError("[WSE-008] 기능 구현이 필요합니다.")
