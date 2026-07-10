"""기능 구현 모듈.

PRAG-008 기능의 실제 구현 위치를 제공한다.
"""

from shared.contracts import FeatureRequest, FeatureResult


async def prag_008(request: FeatureRequest) -> FeatureResult:
    """[PRAG-008] 검색 로그 저장.

    검색 Query, 결과, 점수와 사용 Agent를 기록한다.
    """
    raise NotImplementedError("[PRAG-008] 기능 구현이 필요합니다.")
