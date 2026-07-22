"""기능 구현 모듈.

TR-001, TR-002, TR-003, TR-004 기능의 실제 구현 위치를 제공한다.
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

    리포트 생성기가 생성한 콘텐츠를 다른 언어로 번역한다.
    """
    raise NotImplementedError("[TR-004] 기능 구현이 필요합니다.")
