"""기능 구현 모듈.

SCH-013 기능의 실제 구현 위치를 제공한다.
"""

from shared.contracts import FeatureRequest, FeatureResult


async def sch_013(request: FeatureRequest) -> FeatureResult:
    """[SCH-013] Embedding 재색인.

    Embedding 모델 변경에 따른 재색인을 등록한다.
    """
    raise NotImplementedError("[SCH-013] 기능 구현이 필요합니다.")
