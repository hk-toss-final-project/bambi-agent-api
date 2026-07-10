"""기능 구현 모듈.

DB-021 기능의 실제 구현 위치를 제공한다.
"""

from shared.contracts import FeatureRequest, FeatureResult


async def db_021(request: FeatureRequest) -> FeatureResult:
    """[DB-021] Recommendation Candidate 저장.

    사용자별 추천 후보를 저장한다.
    """
    raise NotImplementedError("[DB-021] 기능 구현이 필요합니다.")
