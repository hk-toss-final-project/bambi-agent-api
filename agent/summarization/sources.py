"""기능 구현 모듈.

SUM-001, SUM-002, SUM-003, SUM-004 기능의 실제 구현 위치를 제공한다.
"""

from shared.contracts import FeatureRequest, FeatureResult


async def sum_001(request: FeatureRequest) -> FeatureResult:
    """[SUM-001] URL 요약.

    URL 본문을 수집하고 요약한다.
    """
    raise NotImplementedError("[SUM-001] 기능 구현이 필요합니다.")


async def sum_002(request: FeatureRequest) -> FeatureResult:
    """[SUM-002] 개인 Wiki 문서 요약.

    사용자 Wiki 문서를 관심사 중심으로 요약한다.
    """
    raise NotImplementedError("[SUM-002] 기능 구현이 필요합니다.")


async def sum_003(request: FeatureRequest) -> FeatureResult:
    """[SUM-003] Global Source 문서 요약.

    외부 수집 문서의 핵심을 요약한다.
    """
    raise NotImplementedError("[SUM-003] 기능 구현이 필요합니다.")


async def sum_004(request: FeatureRequest) -> FeatureResult:
    """[SUM-004] 생성 콘텐츠 요약.

    생성된 긴 콘텐츠를 짧게 요약한다.
    """
    raise NotImplementedError("[SUM-004] 기능 구현이 필요합니다.")
