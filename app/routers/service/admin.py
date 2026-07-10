"""기능 구현 모듈.

SVC-012 기능의 실제 구현 위치를 제공한다.
"""

from shared.contracts import FeatureRequest, FeatureResult


async def svc_012(request: FeatureRequest) -> FeatureResult:
    """[SVC-012] 관리자 설정 변경 요청.

    Prompt, Model, Source 설정 변경을 요청한다.
    """
    raise NotImplementedError("[SVC-012] 기능 구현이 필요합니다.")
