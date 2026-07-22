"""기능 구현 모듈.

REPORT-017 기능의 실제 구현 위치를 제공한다.
"""

from shared.contracts import FeatureRequest, FeatureResult


async def report_017(request: FeatureRequest) -> FeatureResult:
    """[REPORT-017] 콘텐츠 버전 관리.

    생성과 수정 결과를 버전으로 관리한다.
    """
    raise NotImplementedError("[REPORT-017] 기능 구현이 필요합니다.")
