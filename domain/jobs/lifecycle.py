"""기능 구현 모듈.

JOB-001, JOB-002, JOB-003, JOB-004 기능의 실제 구현 위치를 제공한다.
"""

from shared.contracts import FeatureRequest, FeatureResult


async def job_001(request: FeatureRequest) -> FeatureResult:
    """[JOB-001] Agent Job 생성.

    비동기 Agent 작업을 생성하고 Queue에 등록한다.
    """
    raise NotImplementedError("[JOB-001] 기능 구현이 필요합니다.")


async def job_002(request: FeatureRequest) -> FeatureResult:
    """[JOB-002] Agent Job 조회.

    작업의 상태와 진행률을 조회한다.
    """
    raise NotImplementedError("[JOB-002] 기능 구현이 필요합니다.")


async def job_003(request: FeatureRequest) -> FeatureResult:
    """[JOB-003] Agent Job 목록 조회.

    유형, 사용자, 상태별 작업 목록을 조회한다.
    """
    raise NotImplementedError("[JOB-003] 기능 구현이 필요합니다.")


async def job_004(request: FeatureRequest) -> FeatureResult:
    """[JOB-004] Agent Job 취소.

    취소 가능한 작업을 중단한다.
    """
    raise NotImplementedError("[JOB-004] 기능 구현이 필요합니다.")
