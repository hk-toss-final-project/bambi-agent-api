"""Service API 연동 기능 스캐폴드.

전체 기능 명세의 각 기능 ID를 구현할 비동기 함수 계약을 정의한다.
현재 함수 본문은 의도적으로 구현하지 않은 상태이다.
"""

from shared.contracts import FeatureRequest, FeatureResult


# MVP: agent-api-mvp-scope.md에서 구현 대상으로 지정된 기능입니다.
async def svc_001(request: FeatureRequest) -> FeatureResult:
    """[SVC-001] 사용자 컨텍스트 전달.

    서비스 사용자 설정을 Agent 컨텍스트로 전달한다.
    """
    raise NotImplementedError("[SVC-001] 기능 구현이 필요합니다.")


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


# MVP: agent-api-mvp-scope.md에서 구현 대상으로 지정된 기능입니다.
async def svc_008(request: FeatureRequest) -> FeatureResult:
    """[SVC-008] 콘텐츠 생성 요청.

    밤비의 콘텐츠 생성을 요청한다.
    """
    raise NotImplementedError("[SVC-008] 기능 구현이 필요합니다.")


async def svc_009(request: FeatureRequest) -> FeatureResult:
    """[SVC-009] 요약 요청.

    문서 또는 URL 요약을 요청한다.
    """
    raise NotImplementedError("[SVC-009] 기능 구현이 필요합니다.")


async def svc_010(request: FeatureRequest) -> FeatureResult:
    """[SVC-010] 번역 요청.

    콘텐츠 번역을 요청한다.
    """
    raise NotImplementedError("[SVC-010] 기능 구현이 필요합니다.")


async def svc_011(request: FeatureRequest) -> FeatureResult:
    """[SVC-011] 추천 요청.

    사용자별 추천 생성을 요청한다.
    """
    raise NotImplementedError("[SVC-011] 기능 구현이 필요합니다.")


async def svc_012(request: FeatureRequest) -> FeatureResult:
    """[SVC-012] 관리자 설정 변경 요청.

    Prompt, Model, Source 설정 변경을 요청한다.
    """
    raise NotImplementedError("[SVC-012] 기능 구현이 필요합니다.")


# MVP: agent-api-mvp-scope.md에서 구현 대상으로 지정된 기능입니다.
async def svc_013(request: FeatureRequest) -> FeatureResult:
    """[SVC-013] Agent Job 상태 조회.

    비동기 작업 상태를 조회한다.
    """
    raise NotImplementedError("[SVC-013] 기능 구현이 필요합니다.")


# MVP: agent-api-mvp-scope.md에서 구현 대상으로 지정된 기능입니다.
async def svc_014(request: FeatureRequest) -> FeatureResult:
    """[SVC-014] Agent 결과 조회.

    생성 및 처리 결과를 Agent API에서 조회한다.
    """
    raise NotImplementedError("[SVC-014] 기능 구현이 필요합니다.")
