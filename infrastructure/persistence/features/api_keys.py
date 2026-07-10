"""기능 구현 모듈.

DB-028 기능의 실제 구현 위치를 제공한다.
"""

from shared.contracts import FeatureRequest, FeatureResult


async def db_028(request: FeatureRequest) -> FeatureResult:
    """[DB-028] API Key 저장.

    외부 API Key와 Scope 정보를 저장한다.
    """
    raise NotImplementedError("[DB-028] 기능 구현이 필요합니다.")
