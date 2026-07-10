"""기능 구현 모듈.

SCH-001, SCH-002, SCH-003, SCH-004, SCH-005, SCH-006, SCH-007, SCH-008 기능의 실제 구현 위치를 제공한다.
"""

from shared.contracts import FeatureRequest, FeatureResult


async def sch_001(request: FeatureRequest) -> FeatureResult:
    """[SCH-001] RSS 수집 스케줄.

    RSS Source 수집 작업을 정기 등록한다.
    """
    raise NotImplementedError("[SCH-001] 기능 구현이 필요합니다.")


# MVP: agent-api-mvp-scope.md에서 구현 대상으로 지정된 기능입니다.
async def sch_002(request: FeatureRequest) -> FeatureResult:
    """[SCH-002] Naver API 수집 스케줄.

    Naver API 수집 작업을 정기 등록한다.
    """
    raise NotImplementedError("[SCH-002] 기능 구현이 필요합니다.")


# MVP: agent-api-mvp-scope.md에서 구현 대상으로 지정된 기능입니다.
async def sch_003(request: FeatureRequest) -> FeatureResult:
    """[SCH-003] GDELT 수집 스케줄.

    GDELT 수집 작업을 정기 등록한다.
    """
    raise NotImplementedError("[SCH-003] 기능 구현이 필요합니다.")


# MVP: agent-api-mvp-scope.md에서 구현 대상으로 지정된 기능입니다.
async def sch_004(request: FeatureRequest) -> FeatureResult:
    """[SCH-004] NewsAPI 수집 스케줄.

    NewsAPI 수집 작업을 정기 등록한다.
    """
    raise NotImplementedError("[SCH-004] 기능 구현이 필요합니다.")


async def sch_005(request: FeatureRequest) -> FeatureResult:
    """[SCH-005] DART 수집 스케줄.

    DART 수집 작업을 정기 등록한다.
    """
    raise NotImplementedError("[SCH-005] 기능 구현이 필요합니다.")


async def sch_006(request: FeatureRequest) -> FeatureResult:
    """[SCH-006] KRX 수집 스케줄.

    KRX 수집 작업을 정기 등록한다.
    """
    raise NotImplementedError("[SCH-006] 기능 구현이 필요합니다.")


async def sch_007(request: FeatureRequest) -> FeatureResult:
    """[SCH-007] GitHub 수집 스케줄.

    GitHub 수집 작업을 정기 등록한다.
    """
    raise NotImplementedError("[SCH-007] 기능 구현이 필요합니다.")


async def sch_008(request: FeatureRequest) -> FeatureResult:
    """[SCH-008] arXiv 수집 스케줄.

    arXiv 수집 작업을 정기 등록한다.
    """
    raise NotImplementedError("[SCH-008] 기능 구현이 필요합니다.")
