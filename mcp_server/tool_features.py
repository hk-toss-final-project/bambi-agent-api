"""MCP Tool 기능 스캐폴드.

전체 기능 명세의 각 기능 ID를 구현할 비동기 함수 계약을 정의한다.
현재 함수 본문은 의도적으로 구현하지 않은 상태이다.
"""

from shared.contracts import FeatureRequest, FeatureResult


async def mcptool_001(request: FeatureRequest) -> FeatureResult:
    """[MCPTOOL-001] Personal Wiki 검색.

    승인된 사용자의 개인 Wiki를 검색한다.
    """
    raise NotImplementedError("[MCPTOOL-001] 기능 구현이 필요합니다.")


async def mcptool_002(request: FeatureRequest) -> FeatureResult:
    """[MCPTOOL-002] Personal Wiki 문서 조회.

    개인 Wiki의 특정 문서를 조회한다.
    """
    raise NotImplementedError("[MCPTOOL-002] 기능 구현이 필요합니다.")


async def mcptool_003(request: FeatureRequest) -> FeatureResult:
    """[MCPTOOL-003] Personal Wiki Source 추가.

    사용자 승인 하에 Wiki Source를 추가한다.
    """
    raise NotImplementedError("[MCPTOOL-003] 기능 구현이 필요합니다.")


async def mcptool_004(request: FeatureRequest) -> FeatureResult:
    """[MCPTOOL-004] Global Source 검색.

    공용 Global Source Pool을 검색한다.
    """
    raise NotImplementedError("[MCPTOOL-004] 기능 구현이 필요합니다.")


async def mcptool_005(request: FeatureRequest) -> FeatureResult:
    """[MCPTOOL-005] 콘텐츠 요약.

    텍스트, URL, 문서를 요약한다.
    """
    raise NotImplementedError("[MCPTOOL-005] 기능 구현이 필요합니다.")


async def mcptool_006(request: FeatureRequest) -> FeatureResult:
    """[MCPTOOL-006] 콘텐츠 번역.

    콘텐츠를 지정한 언어로 번역한다.
    """
    raise NotImplementedError("[MCPTOOL-006] 기능 구현이 필요합니다.")


async def mcptool_007(request: FeatureRequest) -> FeatureResult:
    """[MCPTOOL-007] 콘텐츠 생성.

    밤비 콘텐츠 생성을 요청한다.
    """
    raise NotImplementedError("[MCPTOOL-007] 기능 구현이 필요합니다.")


async def mcptool_008(request: FeatureRequest) -> FeatureResult:
    """[MCPTOOL-008] 콘텐츠 추천.

    사용자 관심사 기반 추천을 요청한다.
    """
    raise NotImplementedError("[MCPTOOL-008] 기능 구현이 필요합니다.")


async def mcptool_009(request: FeatureRequest) -> FeatureResult:
    """[MCPTOOL-009] 이미지 자료 생성.

    콘텐츠용 이미지 생성을 요청한다.
    """
    raise NotImplementedError("[MCPTOOL-009] 기능 구현이 필요합니다.")


async def mcptool_010(request: FeatureRequest) -> FeatureResult:
    """[MCPTOOL-010] Job 상태 조회.

    비동기 Job의 상태를 조회한다.
    """
    raise NotImplementedError("[MCPTOOL-010] 기능 구현이 필요합니다.")


async def mcptool_011(request: FeatureRequest) -> FeatureResult:
    """[MCPTOOL-011] Global Source 수동 수집.

    권한이 있는 사용자가 Source 수집을 실행한다.
    """
    raise NotImplementedError("[MCPTOOL-011] 기능 구현이 필요합니다.")


async def mcptool_012(request: FeatureRequest) -> FeatureResult:
    """[MCPTOOL-012] Prompt 테스트.

    관리자 권한으로 Prompt를 테스트한다.
    """
    raise NotImplementedError("[MCPTOOL-012] 기능 구현이 필요합니다.")
