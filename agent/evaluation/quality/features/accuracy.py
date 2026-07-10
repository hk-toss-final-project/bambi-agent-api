"""기능 구현 모듈.

QUALITY-002, QUALITY-003, QUALITY-004, QUALITY-005, QUALITY-010, QUALITY-011 기능의 실제 구현 위치를 제공한다.
"""

from shared.contracts import FeatureRequest, FeatureResult


async def quality_002(request: FeatureRequest) -> FeatureResult:
    """[QUALITY-002] 정확성 평가.

    생성 내용이 참조 자료와 일치하는지 평가한다.
    """
    raise NotImplementedError("[QUALITY-002] 기능 구현이 필요합니다.")


async def quality_003(request: FeatureRequest) -> FeatureResult:
    """[QUALITY-003] 근거 충족 평가.

    주요 주장에 충분한 근거가 있는지 평가한다.
    """
    raise NotImplementedError("[QUALITY-003] 기능 구현이 필요합니다.")


async def quality_004(request: FeatureRequest) -> FeatureResult:
    """[QUALITY-004] Citation 평가.

    출처 연결의 정확성과 충분성을 평가한다.
    """
    raise NotImplementedError("[QUALITY-004] 기능 구현이 필요합니다.")


async def quality_005(request: FeatureRequest) -> FeatureResult:
    """[QUALITY-005] 최신성 평가.

    사용된 정보가 콘텐츠 목적에 충분히 최신인지 평가한다.
    """
    raise NotImplementedError("[QUALITY-005] 기능 구현이 필요합니다.")


async def quality_010(request: FeatureRequest) -> FeatureResult:
    """[QUALITY-010] 과도한 추론 검사.

    근거를 넘어선 추론과 과장을 검사한다.
    """
    raise NotImplementedError("[QUALITY-010] 기능 구현이 필요합니다.")


async def quality_011(request: FeatureRequest) -> FeatureResult:
    """[QUALITY-011] Hallucination 검사.

    원문에 없는 정보 생성 가능성을 검사한다.
    """
    raise NotImplementedError("[QUALITY-011] 기능 구현이 필요합니다.")
