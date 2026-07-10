"""기능 구현 모듈.

DB-001 기능의 실제 구현 위치를 제공한다.
"""

from shared.contracts import FeatureRequest, FeatureResult


async def db_001(request: FeatureRequest) -> FeatureResult:
    """[DB-001] 사용자 컨텍스트 저장.

    Agent가 사용할 최소 사용자 컨텍스트를 저장한다.
    """
    raise NotImplementedError("[DB-001] 기능 구현이 필요합니다.")
