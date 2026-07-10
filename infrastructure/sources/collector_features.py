"""Global Source Collector 기능 스캐폴드.

전체 기능 명세의 각 기능 ID를 구현할 비동기 함수 계약을 정의한다.
현재 함수 본문은 의도적으로 구현하지 않은 상태이다.
"""

from shared.contracts import FeatureRequest, FeatureResult


async def col_001(request: FeatureRequest) -> FeatureResult:
    """[COL-001] RSS 수집.

    등록된 RSS Feed에서 신규 콘텐츠를 수집한다.
    """
    raise NotImplementedError("[COL-001] 기능 구현이 필요합니다.")


# MVP: agent-api-mvp-scope.md에서 구현 대상으로 지정된 기능입니다.
async def col_002(request: FeatureRequest) -> FeatureResult:
    """[COL-002] Naver API 수집.

    설정된 키워드로 Naver API 데이터를 수집한다.
    """
    raise NotImplementedError("[COL-002] 기능 구현이 필요합니다.")


# MVP: agent-api-mvp-scope.md에서 구현 대상으로 지정된 기능입니다.
async def col_003(request: FeatureRequest) -> FeatureResult:
    """[COL-003] GDELT 수집.

    글로벌 뉴스와 이벤트 데이터를 수집한다.
    """
    raise NotImplementedError("[COL-003] 기능 구현이 필요합니다.")


# MVP: agent-api-mvp-scope.md에서 구현 대상으로 지정된 기능입니다.
async def col_004(request: FeatureRequest) -> FeatureResult:
    """[COL-004] NewsAPI 수집.

    뉴스 기사와 관련 메타데이터를 수집한다.
    """
    raise NotImplementedError("[COL-004] 기능 구현이 필요합니다.")


async def col_005(request: FeatureRequest) -> FeatureResult:
    """[COL-005] SNS 수집.

    허용된 SNS 공개 데이터를 수집한다.
    """
    raise NotImplementedError("[COL-005] 기능 구현이 필요합니다.")


async def col_006(request: FeatureRequest) -> FeatureResult:
    """[COL-006] 블로그 수집.

    블로그와 공개 게시글 데이터를 수집한다.
    """
    raise NotImplementedError("[COL-006] 기능 구현이 필요합니다.")


async def col_007(request: FeatureRequest) -> FeatureResult:
    """[COL-007] DART 수집.

    기업 공시 데이터를 수집한다.
    """
    raise NotImplementedError("[COL-007] 기능 구현이 필요합니다.")


async def col_008(request: FeatureRequest) -> FeatureResult:
    """[COL-008] KRX 수집.

    시장 및 종목 관련 데이터를 수집한다.
    """
    raise NotImplementedError("[COL-008] 기능 구현이 필요합니다.")


async def col_009(request: FeatureRequest) -> FeatureResult:
    """[COL-009] GitHub 수집.

    Repository, Release, Issue, README 등을 수집한다.
    """
    raise NotImplementedError("[COL-009] 기능 구현이 필요합니다.")


async def col_010(request: FeatureRequest) -> FeatureResult:
    """[COL-010] arXiv 수집.

    논문 메타데이터, 초록, 본문을 수집한다.
    """
    raise NotImplementedError("[COL-010] 기능 구현이 필요합니다.")


async def col_011(request: FeatureRequest) -> FeatureResult:
    """[COL-011] 직접 URL 수집.

    관리자가 지정한 URL의 데이터를 수집한다.
    """
    raise NotImplementedError("[COL-011] 기능 구현이 필요합니다.")


async def col_012(request: FeatureRequest) -> FeatureResult:
    """[COL-012] 사용자 정의 Source 수집.

    추가된 외부 API와 Source Connector를 실행한다.
    """
    raise NotImplementedError("[COL-012] 기능 구현이 필요합니다.")
