"""번역 기능 기능 스캐폴드.

전체 기능 명세의 각 기능 ID를 구현할 비동기 함수 계약을 정의한다.
현재 함수 본문은 의도적으로 구현하지 않은 상태이다.
"""

from shared.contracts import FeatureRequest, FeatureResult


async def tr_001(request: FeatureRequest) -> FeatureResult:
    """[TR-001] 문서 번역.

    전체 문서를 지정 언어로 번역한다.
    """
    raise NotImplementedError("[TR-001] 기능 구현이 필요합니다.")


async def tr_002(request: FeatureRequest) -> FeatureResult:
    """[TR-002] 요약 번역.

    생성된 요약을 지정 언어로 번역한다.
    """
    raise NotImplementedError("[TR-002] 기능 구현이 필요합니다.")


async def tr_003(request: FeatureRequest) -> FeatureResult:
    """[TR-003] 카드 번역.

    카드 제목, 요약, 본문을 번역한다.
    """
    raise NotImplementedError("[TR-003] 기능 구현이 필요합니다.")


async def tr_004(request: FeatureRequest) -> FeatureResult:
    """[TR-004] 생성 콘텐츠 번역.

    밤비가 생성한 콘텐츠를 다른 언어로 번역한다.
    """
    raise NotImplementedError("[TR-004] 기능 구현이 필요합니다.")


async def tr_005(request: FeatureRequest) -> FeatureResult:
    """[TR-005] 다국어 콘텐츠 생성.

    하나의 자료에서 언어별 콘텐츠 버전을 생성한다.
    """
    raise NotImplementedError("[TR-005] 기능 구현이 필요합니다.")


async def tr_006(request: FeatureRequest) -> FeatureResult:
    """[TR-006] 사용자 선호 언어 반영.

    사용자의 기본 언어 설정을 번역에 적용한다.
    """
    raise NotImplementedError("[TR-006] 기능 구현이 필요합니다.")


async def tr_007(request: FeatureRequest) -> FeatureResult:
    """[TR-007] 도메인 용어집 반영.

    기술, 금융 등 분야별 용어를 일관되게 번역한다.
    """
    raise NotImplementedError("[TR-007] 기능 구현이 필요합니다.")


async def tr_008(request: FeatureRequest) -> FeatureResult:
    """[TR-008] Citation 유지.

    번역 후에도 원문 출처 연결을 유지한다.
    """
    raise NotImplementedError("[TR-008] 기능 구현이 필요합니다.")


async def tr_009(request: FeatureRequest) -> FeatureResult:
    """[TR-009] 번역 품질 평가.

    오역, 누락, 고유명사 오류를 검사한다.
    """
    raise NotImplementedError("[TR-009] 기능 구현이 필요합니다.")


async def tr_010(request: FeatureRequest) -> FeatureResult:
    """[TR-010] 언어별 버전 관리.

    콘텐츠의 언어별 버전을 관리한다.
    """
    raise NotImplementedError("[TR-010] 기능 구현이 필요합니다.")
