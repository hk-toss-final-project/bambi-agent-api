"""기능 구현 모듈.

DB-002, DB-003, DB-004, DB-005, DB-006, DB-007 기능의 실제 구현 위치를 제공한다.
"""

from shared.contracts import FeatureRequest, FeatureResult


# MVP: agent-api-mvp-scope.md에서 구현 대상으로 지정된 기능입니다.
async def db_002(request: FeatureRequest) -> FeatureResult:
    """[DB-002] Wiki Source Event 저장.

    개인 Wiki 반영의 근거가 되는 이벤트를 저장한다.
    """
    raise NotImplementedError("[DB-002] 기능 구현이 필요합니다.")


# MVP: agent-api-mvp-scope.md에서 구현 대상으로 지정된 기능입니다.
async def db_003(request: FeatureRequest) -> FeatureResult:
    """[DB-003] 개인 Wiki 문서 저장.

    사용자별 Wiki 문서와 버전을 저장한다.
    """
    raise NotImplementedError("[DB-003] 기능 구현이 필요합니다.")


# MVP: agent-api-mvp-scope.md에서 구현 대상으로 지정된 기능입니다.
async def db_004(request: FeatureRequest) -> FeatureResult:
    """[DB-004] 개인 Wiki Chunk 저장.

    개인 Wiki 검색용 Chunk를 저장한다.
    """
    raise NotImplementedError("[DB-004] 기능 구현이 필요합니다.")


# MVP: agent-api-mvp-scope.md에서 구현 대상으로 지정된 기능입니다.
async def db_005(request: FeatureRequest) -> FeatureResult:
    """[DB-005] 개인 Wiki Embedding 저장.

    개인 Wiki의 Vector 데이터를 저장한다.
    """
    raise NotImplementedError("[DB-005] 기능 구현이 필요합니다.")


async def db_006(request: FeatureRequest) -> FeatureResult:
    """[DB-006] 개인 Wiki Version 저장.

    개인 Wiki 재구성 버전을 저장한다.
    """
    raise NotImplementedError("[DB-006] 기능 구현이 필요합니다.")


async def db_007(request: FeatureRequest) -> FeatureResult:
    """[DB-007] 사용자 관심사 저장.

    관심사 프로필, 계층, 관계를 저장한다.
    """
    raise NotImplementedError("[DB-007] 기능 구현이 필요합니다.")
