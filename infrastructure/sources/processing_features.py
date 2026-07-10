"""Global Source 정제 및 저장 기능 스캐폴드.

전체 기능 명세의 각 기능 ID를 구현할 비동기 함수 계약을 정의한다.
현재 함수 본문은 의도적으로 구현하지 않은 상태이다.
"""

from shared.contracts import FeatureRequest, FeatureResult


async def gsp_001(request: FeatureRequest) -> FeatureResult:
    """[GSP-001] Raw 데이터 저장.

    외부 Source에서 받은 원본 데이터를 저장한다.
    """
    raise NotImplementedError("[GSP-001] 기능 구현이 필요합니다.")


async def gsp_002(request: FeatureRequest) -> FeatureResult:
    """[GSP-002] HTML 본문 추출.

    HTML 페이지에서 주요 본문을 추출한다.
    """
    raise NotImplementedError("[GSP-002] 기능 구현이 필요합니다.")


async def gsp_003(request: FeatureRequest) -> FeatureResult:
    """[GSP-003] PDF 본문 추출.

    PDF 문서에서 텍스트와 구조를 추출한다.
    """
    raise NotImplementedError("[GSP-003] 기능 구현이 필요합니다.")


# MVP: agent-api-mvp-scope.md에서 구현 대상으로 지정된 기능입니다.
async def gsp_004(request: FeatureRequest) -> FeatureResult:
    """[GSP-004] API 응답 정규화.

    Source별 응답을 공통 문서 구조로 변환한다.
    """
    raise NotImplementedError("[GSP-004] 기능 구현이 필요합니다.")


async def gsp_005(request: FeatureRequest) -> FeatureResult:
    """[GSP-005] 문서 언어 감지.

    수집된 문서의 언어를 판별한다.
    """
    raise NotImplementedError("[GSP-005] 기능 구현이 필요합니다.")


# MVP: agent-api-mvp-scope.md에서 구현 대상으로 지정된 기능입니다.
async def gsp_006(request: FeatureRequest) -> FeatureResult:
    """[GSP-006] 문서 중복 제거.

    동일 URL과 유사 문서를 중복 제거한다.
    """
    raise NotImplementedError("[GSP-006] 기능 구현이 필요합니다.")


async def gsp_007(request: FeatureRequest) -> FeatureResult:
    """[GSP-007] 문서 품질 필터링.

    스팸, 빈 문서, 깨진 콘텐츠를 제외한다.
    """
    raise NotImplementedError("[GSP-007] 기능 구현이 필요합니다.")


async def gsp_008(request: FeatureRequest) -> FeatureResult:
    """[GSP-008] 문서 버전 관리.

    외부 문서 변경 이력을 관리한다.
    """
    raise NotImplementedError("[GSP-008] 기능 구현이 필요합니다.")


async def gsp_009(request: FeatureRequest) -> FeatureResult:
    """[GSP-009] Global 문서 Chunking.

    Global Source 문서를 검색 가능한 Chunk로 분할한다.
    """
    raise NotImplementedError("[GSP-009] 기능 구현이 필요합니다.")


async def gsp_010(request: FeatureRequest) -> FeatureResult:
    """[GSP-010] Global 문서 Embedding.

    Global Source 검색용 Vector를 생성한다.
    """
    raise NotImplementedError("[GSP-010] 기능 구현이 필요합니다.")


async def gsp_011(request: FeatureRequest) -> FeatureResult:
    """[GSP-011] Global Vector Index 관리.

    Global Source 전용 Vector Index를 관리한다.
    """
    raise NotImplementedError("[GSP-011] 기능 구현이 필요합니다.")


async def gsp_012(request: FeatureRequest) -> FeatureResult:
    """[GSP-012] Source 신뢰도 관리.

    Source별 품질과 신뢰도 정보를 관리한다.
    """
    raise NotImplementedError("[GSP-012] 기능 구현이 필요합니다.")


async def gsp_013(request: FeatureRequest) -> FeatureResult:
    """[GSP-013] 수집 이력 관리.

    수집 실행 결과와 신규·중복·실패 건수를 기록한다.
    """
    raise NotImplementedError("[GSP-013] 기능 구현이 필요합니다.")


async def gsp_014(request: FeatureRequest) -> FeatureResult:
    """[GSP-014] 오래된 데이터 보존 정책.

    수집 데이터의 보존과 만료 정책을 적용한다.
    """
    raise NotImplementedError("[GSP-014] 기능 구현이 필요합니다.")


# MVP: agent-api-mvp-scope.md에서 구현 대상으로 지정된 기능입니다.
async def gsp_015(request: FeatureRequest) -> FeatureResult:
    """[GSP-015] 개인 Wiki 자동 반영 금지.

    수집 데이터를 사용자 선택 없이 개인 Wiki에 반영하지 않는다.
    """
    raise NotImplementedError("[GSP-015] 기능 구현이 필요합니다.")
