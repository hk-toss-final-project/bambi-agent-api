"""기능 구현 모듈.

OBS-012, OBS-013, OBS-014 기능의 실제 구현 위치를 제공한다.
"""

from shared.contracts import FeatureRequest, FeatureResult


async def obs_012(request: FeatureRequest) -> FeatureResult:
    """[OBS-012] Token Usage 로그.

    작업별 입력·출력 Token을 기록한다.
    """
    raise NotImplementedError("[OBS-012] 기능 구현이 필요합니다.")


async def obs_013(request: FeatureRequest) -> FeatureResult:
    """[OBS-013] Provider Usage 로그.

    외부 Provider 사용량과 오류를 기록한다.
    """
    raise NotImplementedError("[OBS-013] 기능 구현이 필요합니다.")


async def obs_014(request: FeatureRequest) -> FeatureResult:
    """[OBS-014] 비용 추적.

    기능, 사용자, Provider별 비용을 계산한다.
    """
    raise NotImplementedError("[OBS-014] 기능 구현이 필요합니다.")
