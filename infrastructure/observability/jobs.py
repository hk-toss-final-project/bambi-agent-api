"""기능 구현 모듈.

OBS-002, OBS-003, OBS-004 기능의 실제 구현 위치를 제공한다.
"""

from shared.contracts import FeatureRequest, FeatureResult


async def obs_002(request: FeatureRequest) -> FeatureResult:
    """[OBS-002] Agent Job 로그.

    비동기 작업의 실행 단계를 기록한다.
    """
    raise NotImplementedError("[OBS-002] 기능 구현이 필요합니다.")


async def obs_003(request: FeatureRequest) -> FeatureResult:
    """[OBS-003] Worker 실행 로그.

    Worker별 처리 결과와 오류를 기록한다.
    """
    raise NotImplementedError("[OBS-003] 기능 구현이 필요합니다.")


async def obs_004(request: FeatureRequest) -> FeatureResult:
    """[OBS-004] Scheduler 실행 로그.

    스케줄 실행과 Job 등록 결과를 기록한다.
    """
    raise NotImplementedError("[OBS-004] 기능 구현이 필요합니다.")
