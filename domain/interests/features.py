"""사용자 관심사 분류 기능 스캐폴드.

전체 기능 명세의 각 기능 ID를 구현할 비동기 함수 계약을 정의한다.
현재 함수 본문은 의도적으로 구현하지 않은 상태이다.
"""

from shared.contracts import FeatureRequest, FeatureResult


# MVP: agent-api-mvp-scope.md에서 구현 대상으로 지정된 기능입니다.
async def int_001(request: FeatureRequest) -> FeatureResult:
    """[INT-001] 관심사 Topic 추출.

    개인 Wiki와 사용자 행동에서 관심 주제를 추출한다.
    """
    raise NotImplementedError("[INT-001] 기능 구현이 필요합니다.")


# MVP: agent-api-mvp-scope.md에서 구현 대상으로 지정된 기능입니다.
async def int_002(request: FeatureRequest) -> FeatureResult:
    """[INT-002] 관심사 Category 분류.

    관심사를 서비스의 분류 체계에 매핑한다.
    """
    raise NotImplementedError("[INT-002] 기능 구현이 필요합니다.")


async def int_003(request: FeatureRequest) -> FeatureResult:
    """[INT-003] 관심사 계층 구성.

    상위 관심사와 세부 관심사 구조를 구성한다.
    """
    raise NotImplementedError("[INT-003] 기능 구현이 필요합니다.")


async def int_004(request: FeatureRequest) -> FeatureResult:
    """[INT-004] 관심사 간 관계 구성.

    서로 관련된 관심사 간 연결 관계를 생성한다.
    """
    raise NotImplementedError("[INT-004] 기능 구현이 필요합니다.")


# MVP: agent-api-mvp-scope.md에서 구현 대상으로 지정된 기능입니다.
async def int_005(request: FeatureRequest) -> FeatureResult:
    """[INT-005] 관심사 점수 계산.

    사용자 행동 강도와 최신성을 기반으로 점수를 계산한다.
    """
    raise NotImplementedError("[INT-005] 기능 구현이 필요합니다.")


async def int_006(request: FeatureRequest) -> FeatureResult:
    """[INT-006] 관심사 Confidence 계산.

    추론된 관심사의 신뢰도를 계산한다.
    """
    raise NotImplementedError("[INT-006] 기능 구현이 필요합니다.")


async def int_007(request: FeatureRequest) -> FeatureResult:
    """[INT-007] 관심사 근거 추적.

    관심사를 만든 Wiki 문서와 사용자 행동을 연결한다.
    """
    raise NotImplementedError("[INT-007] 기능 구현이 필요합니다.")


async def int_008(request: FeatureRequest) -> FeatureResult:
    """[INT-008] 관심사 시간 감쇠.

    오래된 관심사의 가중치를 점진적으로 낮춘다.
    """
    raise NotImplementedError("[INT-008] 기능 구현이 필요합니다.")


async def int_009(request: FeatureRequest) -> FeatureResult:
    """[INT-009] 비선호 관심사 반영.

    숨김, 차단, 신고 등의 부정 신호를 반영한다.
    """
    raise NotImplementedError("[INT-009] 기능 구현이 필요합니다.")


async def int_010(request: FeatureRequest) -> FeatureResult:
    """[INT-010] 관심사 프로필 버전 관리.

    관심사 프로필의 변경 이력을 관리한다.
    """
    raise NotImplementedError("[INT-010] 기능 구현이 필요합니다.")


# MVP: agent-api-mvp-scope.md에서 구현 대상으로 지정된 기능입니다.
async def int_011(request: FeatureRequest) -> FeatureResult:
    """[INT-011] 관심사 프로필 재계산.

    Wiki 변경 시 관심사 구조와 점수를 다시 계산한다.
    """
    raise NotImplementedError("[INT-011] 기능 구현이 필요합니다.")
