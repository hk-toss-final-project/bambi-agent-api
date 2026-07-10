"""기능 구현 모듈.

SEC-019, SEC-020 기능의 실제 구현 위치를 제공한다.
"""

from shared.contracts import FeatureRequest, FeatureResult


async def sec_019(request: FeatureRequest) -> FeatureResult:
    """[SEC-019] 접근 Audit Log.

    Personal Wiki와 민감 기능 접근 이력을 기록한다.
    """
    raise NotImplementedError("[SEC-019] 기능 구현이 필요합니다.")


async def sec_020(request: FeatureRequest) -> FeatureResult:
    """[SEC-020] 관리자 변경 Audit Log.

    설정과 정책 변경 내역을 기록한다.
    """
    raise NotImplementedError("[SEC-020] 기능 구현이 필요합니다.")
