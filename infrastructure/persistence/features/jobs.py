"""기능 구현 모듈.

DB-026 기능의 실제 구현 위치를 제공한다.
"""

from shared.contracts import FeatureRequest, FeatureResult


async def db_026(request: FeatureRequest) -> FeatureResult:
    """[DB-026] Agent Job 저장.

    비동기 작업 상태와 결과를 저장한다.
    """
    raise NotImplementedError("[DB-026] 기능 구현이 필요합니다.")
