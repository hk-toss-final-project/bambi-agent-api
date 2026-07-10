"""기능 구현 모듈.

DB-027 기능의 실제 구현 위치를 제공한다.
"""

from shared.contracts import FeatureRequest, FeatureResult


async def db_027(request: FeatureRequest) -> FeatureResult:
    """[DB-027] Event Outbox 저장.

    발행 예정 이벤트를 저장한다.
    """
    raise NotImplementedError("[DB-027] 기능 구현이 필요합니다.")
