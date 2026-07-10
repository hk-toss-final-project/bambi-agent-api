"""기능 구현 모듈.

ADMIN-001, ADMIN-002, ADMIN-003, ADMIN-004, ADMIN-005 기능의 실제 구현 위치를 제공한다.
"""

from shared.contracts import FeatureRequest, FeatureResult


async def admin_001(request: FeatureRequest) -> FeatureResult:
    """[ADMIN-001] Prompt 관리.

    Prompt Template과 버전을 관리한다.
    """
    raise NotImplementedError("[ADMIN-001] 기능 구현이 필요합니다.")


async def admin_002(request: FeatureRequest) -> FeatureResult:
    """[ADMIN-002] Model Config 관리.

    모델 실행 설정과 라우팅 정책을 관리한다.
    """
    raise NotImplementedError("[ADMIN-002] 기능 구현이 필요합니다.")


async def admin_003(request: FeatureRequest) -> FeatureResult:
    """[ADMIN-003] Retrieval 설정 관리.

    검색과 RAG 정책을 관리한다.
    """
    raise NotImplementedError("[ADMIN-003] 기능 구현이 필요합니다.")


async def admin_004(request: FeatureRequest) -> FeatureResult:
    """[ADMIN-004] Embedding 설정 관리.

    Embedding 모델과 색인 정책을 관리한다.
    """
    raise NotImplementedError("[ADMIN-004] 기능 구현이 필요합니다.")


async def admin_005(request: FeatureRequest) -> FeatureResult:
    """[ADMIN-005] Generation Policy 관리.

    플랜별 콘텐츠 생성 정책을 관리한다.
    """
    raise NotImplementedError("[ADMIN-005] 기능 구현이 필요합니다.")
