"""Retrieval 설정 관리 기능 스캐폴드.

전체 기능 명세의 각 기능 ID를 구현할 비동기 함수 계약을 정의한다.
현재 함수 본문은 의도적으로 구현하지 않은 상태이다.
"""

from shared.contracts import FeatureRequest, FeatureResult


async def ret_001(request: FeatureRequest) -> FeatureResult:
    """[RET-001] Keyword Search 설정.

    키워드 검색 방식과 가중치를 설정한다.
    """
    raise NotImplementedError("[RET-001] 기능 구현이 필요합니다.")


async def ret_002(request: FeatureRequest) -> FeatureResult:
    """[RET-002] Vector Search 설정.

    Vector 검색 방식과 Threshold를 설정한다.
    """
    raise NotImplementedError("[RET-002] 기능 구현이 필요합니다.")


async def ret_003(request: FeatureRequest) -> FeatureResult:
    """[RET-003] Hybrid Search 설정.

    Keyword와 Vector 검색 결합 정책을 설정한다.
    """
    raise NotImplementedError("[RET-003] 기능 구현이 필요합니다.")


async def ret_004(request: FeatureRequest) -> FeatureResult:
    """[RET-004] Top-K 설정.

    검색 결과로 사용할 문서 수를 설정한다.
    """
    raise NotImplementedError("[RET-004] 기능 구현이 필요합니다.")


async def ret_005(request: FeatureRequest) -> FeatureResult:
    """[RET-005] Reranking 설정.

    검색 결과 재정렬 모델과 정책을 설정한다.
    """
    raise NotImplementedError("[RET-005] 기능 구현이 필요합니다.")


async def ret_006(request: FeatureRequest) -> FeatureResult:
    """[RET-006] Chunk 설정.

    문서 분할 크기와 중첩 기준을 설정한다.
    """
    raise NotImplementedError("[RET-006] 기능 구현이 필요합니다.")


async def ret_007(request: FeatureRequest) -> FeatureResult:
    """[RET-007] Embedding 설정.

    Embedding 모델과 버전을 설정한다.
    """
    raise NotImplementedError("[RET-007] 기능 구현이 필요합니다.")


async def ret_008(request: FeatureRequest) -> FeatureResult:
    """[RET-008] Citation 설정.

    출처 표시와 검증 정책을 설정한다.
    """
    raise NotImplementedError("[RET-008] 기능 구현이 필요합니다.")


async def ret_009(request: FeatureRequest) -> FeatureResult:
    """[RET-009] Personal Wiki 검색 범위.

    개인 Wiki 검색 깊이와 범위를 설정한다.
    """
    raise NotImplementedError("[RET-009] 기능 구현이 필요합니다.")


async def ret_010(request: FeatureRequest) -> FeatureResult:
    """[RET-010] Global Source 검색 범위.

    Global Source 검색 깊이와 범위를 설정한다.
    """
    raise NotImplementedError("[RET-010] 기능 구현이 필요합니다.")


async def ret_011(request: FeatureRequest) -> FeatureResult:
    """[RET-011] 플랜별 Retrieval 정책.

    무료와 유료 플랜의 검색 범위를 다르게 설정한다.
    """
    raise NotImplementedError("[RET-011] 기능 구현이 필요합니다.")
