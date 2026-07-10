"""기능 구현 모듈.

PWE-001, PWE-002, PWE-003, PWE-009 기능의 실제 구현 위치를 제공한다.
"""

from shared.contracts import FeatureRequest, FeatureResult


# MVP: agent-api-mvp-scope.md에서 구현 대상으로 지정된 기능입니다.
async def pwe_001(request: FeatureRequest) -> FeatureResult:
    """[PWE-001] 개인 Wiki 문서 Chunking.

    Wiki 문서를 의미 단위 Chunk로 분할한다.
    """
    raise NotImplementedError("[PWE-001] 기능 구현이 필요합니다.")


async def pwe_002(request: FeatureRequest) -> FeatureResult:
    """[PWE-002] Chunk 저장.

    생성된 Chunk를 문서 버전과 연결해 저장한다.
    """
    raise NotImplementedError("[PWE-002] 기능 구현이 필요합니다.")


async def pwe_003(request: FeatureRequest) -> FeatureResult:
    """[PWE-003] Chunk Metadata 관리.

    관심사, 출처, 문서 버전 등의 정보를 관리한다.
    """
    raise NotImplementedError("[PWE-003] 기능 구현이 필요합니다.")


async def pwe_009(request: FeatureRequest) -> FeatureResult:
    """[PWE-009] 불필요 Chunk 제거.

    광고, 메뉴, 반복 문구 등 검색에 불필요한 Chunk를 제거한다.
    """
    raise NotImplementedError("[PWE-009] 기능 구현이 필요합니다.")
