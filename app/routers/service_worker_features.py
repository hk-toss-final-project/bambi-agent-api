"""Service Worker 연동 기능 스캐폴드.

전체 기능 명세의 각 기능 ID를 구현할 비동기 함수 계약을 정의한다.
현재 함수 본문은 의도적으로 구현하지 않은 상태이다.
"""

from shared.contracts import FeatureRequest, FeatureResult


# MVP: agent-api-mvp-scope.md에서 구현 대상으로 지정된 기능입니다.
async def sw_001(request: FeatureRequest) -> FeatureResult:
    """[SW-001] Content Ready 이벤트 수신.

    발행 가능한 콘텐츠 이벤트를 소비한다.
    """
    raise NotImplementedError("[SW-001] 기능 구현이 필요합니다.")


async def sw_002(request: FeatureRequest) -> FeatureResult:
    """[SW-002] Recommendation Ready 이벤트 수신.

    추천 결과 이벤트를 소비한다.
    """
    raise NotImplementedError("[SW-002] 기능 구현이 필요합니다.")


async def sw_003(request: FeatureRequest) -> FeatureResult:
    """[SW-003] Image Asset Ready 이벤트 수신.

    이미지 생성 완료 이벤트를 소비한다.
    """
    raise NotImplementedError("[SW-003] 기능 구현이 필요합니다.")


# MVP: agent-api-mvp-scope.md에서 구현 대상으로 지정된 기능입니다.
async def sw_004(request: FeatureRequest) -> FeatureResult:
    """[SW-004] Publish Snapshot 조회.

    Agent API에서 서비스 저장용 콘텐츠를 조회한다.
    """
    raise NotImplementedError("[SW-004] 기능 구현이 필요합니다.")


async def sw_005(request: FeatureRequest) -> FeatureResult:
    """[SW-005] 발행 가능 상태 검증.

    콘텐츠가 실제 발행 가능한 상태인지 확인한다.
    """
    raise NotImplementedError("[SW-005] 기능 구현이 필요합니다.")


async def sw_006(request: FeatureRequest) -> FeatureResult:
    """[SW-006] 콘텐츠 Version 검증.

    오래된 콘텐츠 버전이 반영되지 않도록 확인한다.
    """
    raise NotImplementedError("[SW-006] 기능 구현이 필요합니다.")


# MVP: agent-api-mvp-scope.md에서 구현 대상으로 지정된 기능입니다.
async def sw_007(request: FeatureRequest) -> FeatureResult:
    """[SW-007] service-db 콘텐츠 Upsert.

    콘텐츠 발행본을 service-db에 저장하거나 갱신한다.
    """
    raise NotImplementedError("[SW-007] 기능 구현이 필요합니다.")


async def sw_008(request: FeatureRequest) -> FeatureResult:
    """[SW-008] service-db 피드 Upsert.

    발행 콘텐츠를 사용자 피드에 반영한다.
    """
    raise NotImplementedError("[SW-008] 기능 구현이 필요합니다.")


# MVP: agent-api-mvp-scope.md에서 구현 대상으로 지정된 기능입니다.
async def sw_009(request: FeatureRequest) -> FeatureResult:
    """[SW-009] 발행 완료 ACK.

    service-db 반영 완료를 Agent API에 알린다.
    """
    raise NotImplementedError("[SW-009] 기능 구현이 필요합니다.")


async def sw_010(request: FeatureRequest) -> FeatureResult:
    """[SW-010] 발행 실패 전달.

    발행 실패 사유를 Agent API에 전달한다.
    """
    raise NotImplementedError("[SW-010] 기능 구현이 필요합니다.")


async def sw_011(request: FeatureRequest) -> FeatureResult:
    """[SW-011] 이벤트 중복 처리 방지.

    동일 이벤트가 여러 번 반영되지 않도록 한다.
    """
    raise NotImplementedError("[SW-011] 기능 구현이 필요합니다.")


async def sw_012(request: FeatureRequest) -> FeatureResult:
    """[SW-012] 오래된 이벤트 무시.

    최신 버전보다 오래된 이벤트를 무시한다.
    """
    raise NotImplementedError("[SW-012] 기능 구현이 필요합니다.")


async def sw_013(request: FeatureRequest) -> FeatureResult:
    """[SW-013] 콘텐츠 무결성 검증.

    Snapshot의 Hash와 버전을 확인한다.
    """
    raise NotImplementedError("[SW-013] 기능 구현이 필요합니다.")
