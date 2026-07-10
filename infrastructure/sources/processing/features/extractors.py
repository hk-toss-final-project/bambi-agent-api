"""기능 구현 모듈.

GSP-002, GSP-003 기능의 실제 구현 위치를 제공한다.
"""

from shared.contracts import FeatureRequest, FeatureResult


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
