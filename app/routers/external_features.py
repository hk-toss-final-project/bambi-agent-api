"""External Agent API 기능 스캐폴드.

전체 기능 명세의 각 기능 ID를 구현할 비동기 함수 계약을 정의한다.
현재 함수 본문은 의도적으로 구현하지 않은 상태이다.
"""

from shared.contracts import FeatureRequest, FeatureResult


async def ext_001(request: FeatureRequest) -> FeatureResult:
    """[EXT-001] 외부 요약 API.

    외부 시스템에 문서와 URL 요약 기능을 제공한다.
    """
    raise NotImplementedError("[EXT-001] 기능 구현이 필요합니다.")


async def ext_002(request: FeatureRequest) -> FeatureResult:
    """[EXT-002] 외부 번역 API.

    외부 시스템에 번역 기능을 제공한다.
    """
    raise NotImplementedError("[EXT-002] 기능 구현이 필요합니다.")


async def ext_003(request: FeatureRequest) -> FeatureResult:
    """[EXT-003] 외부 콘텐츠 생성 API.

    외부 시스템에서 콘텐츠 생성을 요청할 수 있게 한다.
    """
    raise NotImplementedError("[EXT-003] 기능 구현이 필요합니다.")


async def ext_004(request: FeatureRequest) -> FeatureResult:
    """[EXT-004] 외부 Global Search API.

    Global Source Pool 검색 기능을 제공한다.
    """
    raise NotImplementedError("[EXT-004] 기능 구현이 필요합니다.")


async def ext_005(request: FeatureRequest) -> FeatureResult:
    """[EXT-005] 외부 Personal Wiki Search API.

    사용자 승인이 있는 개인 Wiki 검색을 제공한다.
    """
    raise NotImplementedError("[EXT-005] 기능 구현이 필요합니다.")


async def ext_006(request: FeatureRequest) -> FeatureResult:
    """[EXT-006] 외부 추천 API.

    사용자 컨텍스트 기반 추천 기능을 제공한다.
    """
    raise NotImplementedError("[EXT-006] 기능 구현이 필요합니다.")


async def ext_007(request: FeatureRequest) -> FeatureResult:
    """[EXT-007] 외부 이미지 생성 API.

    외부 시스템에 이미지 생성 기능을 제공한다.
    """
    raise NotImplementedError("[EXT-007] 기능 구현이 필요합니다.")


async def ext_008(request: FeatureRequest) -> FeatureResult:
    """[EXT-008] 외부 Job 상태 조회.

    비동기 작업 상태와 결과를 조회한다.
    """
    raise NotImplementedError("[EXT-008] 기능 구현이 필요합니다.")


async def ext_009(request: FeatureRequest) -> FeatureResult:
    """[EXT-009] 외부 Webhook Callback.

    작업 완료 결과를 외부 시스템에 전달한다.
    """
    raise NotImplementedError("[EXT-009] 기능 구현이 필요합니다.")


async def ext_010(request: FeatureRequest) -> FeatureResult:
    """[EXT-010] API Scope 검증.

    요청 기능에 필요한 Scope를 확인한다.
    """
    raise NotImplementedError("[EXT-010] 기능 구현이 필요합니다.")


async def ext_011(request: FeatureRequest) -> FeatureResult:
    """[EXT-011] API Quota 검증.

    API Key의 사용량 한도를 확인한다.
    """
    raise NotImplementedError("[EXT-011] 기능 구현이 필요합니다.")


async def ext_012(request: FeatureRequest) -> FeatureResult:
    """[EXT-012] API Rate Limit.

    외부 호출량을 제한한다.
    """
    raise NotImplementedError("[EXT-012] 기능 구현이 필요합니다.")


async def ext_013(request: FeatureRequest) -> FeatureResult:
    """[EXT-013] 외부 호출 로그.

    외부 API 요청과 결과를 기록한다.
    """
    raise NotImplementedError("[EXT-013] 기능 구현이 필요합니다.")


async def ext_014(request: FeatureRequest) -> FeatureResult:
    """[EXT-014] 외부 사용량 기록.

    외부 고객별 Token과 비용을 기록한다.
    """
    raise NotImplementedError("[EXT-014] 기능 구현이 필요합니다.")
