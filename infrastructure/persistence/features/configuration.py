"""기능 구현 모듈.

DB-022, DB-023, DB-024, DB-025 기능의 실제 구현 위치를 제공한다.
"""

from shared.contracts import FeatureRequest, FeatureResult


async def db_022(request: FeatureRequest) -> FeatureResult:
    """[DB-022] Prompt 저장.

    Prompt Template과 버전을 저장한다.
    """
    raise NotImplementedError("[DB-022] 기능 구현이 필요합니다.")


async def db_023(request: FeatureRequest) -> FeatureResult:
    """[DB-023] Model Config 저장.

    모델 설정과 버전을 저장한다.
    """
    raise NotImplementedError("[DB-023] 기능 구현이 필요합니다.")


async def db_024(request: FeatureRequest) -> FeatureResult:
    """[DB-024] Retrieval 설정 저장.

    검색과 RAG 설정을 저장한다.
    """
    raise NotImplementedError("[DB-024] 기능 구현이 필요합니다.")


async def db_025(request: FeatureRequest) -> FeatureResult:
    """[DB-025] Embedding 설정 저장.

    Embedding 모델과 정책을 저장한다.
    """
    raise NotImplementedError("[DB-025] 기능 구현이 필요합니다.")
