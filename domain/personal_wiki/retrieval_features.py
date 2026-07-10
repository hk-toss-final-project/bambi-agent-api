"""개인 Wiki 검색 및 RAG 기능 스캐폴드.

전체 기능 명세의 각 기능 ID를 구현할 비동기 함수 계약을 정의한다.
현재 함수 본문은 의도적으로 구현하지 않은 상태이다.
"""

from shared.contracts import FeatureRequest, FeatureResult


async def prag_001(request: FeatureRequest) -> FeatureResult:
    """[PRAG-001] Keyword Search.

    개인 Wiki에서 키워드 기반 검색을 수행한다.
    """
    raise NotImplementedError("[PRAG-001] 기능 구현이 필요합니다.")


async def prag_002(request: FeatureRequest) -> FeatureResult:
    """[PRAG-002] Vector Search.

    개인 Wiki에서 의미 유사도 검색을 수행한다.
    """
    raise NotImplementedError("[PRAG-002] 기능 구현이 필요합니다.")


# MVP: agent-api-mvp-scope.md에서 구현 대상으로 지정된 기능입니다.
async def prag_003(request: FeatureRequest) -> FeatureResult:
    """[PRAG-003] Hybrid Search.

    Keyword와 Vector 검색 결과를 결합한다.
    """
    raise NotImplementedError("[PRAG-003] 기능 구현이 필요합니다.")


async def prag_004(request: FeatureRequest) -> FeatureResult:
    """[PRAG-004] 검색 결과 Reranking.

    사용자 관심사와 요청 목적을 기준으로 결과를 재정렬한다.
    """
    raise NotImplementedError("[PRAG-004] 기능 구현이 필요합니다.")


async def prag_005(request: FeatureRequest) -> FeatureResult:
    """[PRAG-005] 사용자 관심사 기반 검색.

    관심사 프로필을 검색 조건에 반영한다.
    """
    raise NotImplementedError("[PRAG-005] 기능 구현이 필요합니다.")


# MVP: agent-api-mvp-scope.md에서 구현 대상으로 지정된 기능입니다.
async def prag_006(request: FeatureRequest) -> FeatureResult:
    """[PRAG-006] 개인 Wiki Context 구성.

    LLM 입력에 사용할 개인 Wiki Context를 구성한다.
    """
    raise NotImplementedError("[PRAG-006] 기능 구현이 필요합니다.")


# MVP: agent-api-mvp-scope.md에서 구현 대상으로 지정된 기능입니다.
async def prag_007(request: FeatureRequest) -> FeatureResult:
    """[PRAG-007] Citation 연결.

    생성 결과와 참조한 개인 Wiki 문서를 연결한다.
    """
    raise NotImplementedError("[PRAG-007] 기능 구현이 필요합니다.")


async def prag_008(request: FeatureRequest) -> FeatureResult:
    """[PRAG-008] 검색 로그 저장.

    검색 Query, 결과, 점수와 사용 Agent를 기록한다.
    """
    raise NotImplementedError("[PRAG-008] 기능 구현이 필요합니다.")


async def prag_009(request: FeatureRequest) -> FeatureResult:
    """[PRAG-009] 검색 품질 평가.

    개인 Wiki 검색 결과의 적합성을 평가한다.
    """
    raise NotImplementedError("[PRAG-009] 기능 구현이 필요합니다.")
