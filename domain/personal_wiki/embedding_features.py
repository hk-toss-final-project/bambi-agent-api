"""개인 Wiki Chunk 및 Embedding 기능 스캐폴드.

전체 기능 명세의 각 기능 ID를 구현할 비동기 함수 계약을 정의한다.
현재 함수 본문은 의도적으로 구현하지 않은 상태이다.
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


# MVP: agent-api-mvp-scope.md에서 구현 대상으로 지정된 기능입니다.
async def pwe_004(request: FeatureRequest) -> FeatureResult:
    """[PWE-004] Embedding 생성.

    개인 Wiki Chunk의 Vector를 생성한다.
    """
    raise NotImplementedError("[PWE-004] 기능 구현이 필요합니다.")


# MVP: agent-api-mvp-scope.md에서 구현 대상으로 지정된 기능입니다.
async def pwe_005(request: FeatureRequest) -> FeatureResult:
    """[PWE-005] Embedding 저장.

    사용자별 Vector 검색 저장소에 Embedding을 저장한다.
    """
    raise NotImplementedError("[PWE-005] 기능 구현이 필요합니다.")


async def pwe_006(request: FeatureRequest) -> FeatureResult:
    """[PWE-006] Embedding 갱신.

    문서 변경 시 관련 Embedding을 갱신한다.
    """
    raise NotImplementedError("[PWE-006] 기능 구현이 필요합니다.")


async def pwe_007(request: FeatureRequest) -> FeatureResult:
    """[PWE-007] Embedding 재생성.

    모델 또는 Chunk 정책 변경 시 재생성한다.
    """
    raise NotImplementedError("[PWE-007] 기능 구현이 필요합니다.")


async def pwe_008(request: FeatureRequest) -> FeatureResult:
    """[PWE-008] Vector Namespace 분리.

    사용자별 Vector 검색 범위를 분리한다.
    """
    raise NotImplementedError("[PWE-008] 기능 구현이 필요합니다.")


async def pwe_009(request: FeatureRequest) -> FeatureResult:
    """[PWE-009] 불필요 Chunk 제거.

    광고, 메뉴, 반복 문구 등 검색에 불필요한 Chunk를 제거한다.
    """
    raise NotImplementedError("[PWE-009] 기능 구현이 필요합니다.")


async def pwe_010(request: FeatureRequest) -> FeatureResult:
    """[PWE-010] 삭제 Vector 반영.

    문서 삭제 시 관련 Vector도 검색 대상에서 제거한다.
    """
    raise NotImplementedError("[PWE-010] 기능 구현이 필요합니다.")
