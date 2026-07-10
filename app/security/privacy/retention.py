"""기능 구현 모듈.

SEC-018 기능의 실제 구현 위치를 제공한다.
"""

from shared.contracts import FeatureRequest, FeatureResult


async def sec_018(request: FeatureRequest) -> FeatureResult:
    """[SEC-018] 데이터 보존 기간 관리.

    데이터 유형별 보존과 파기 정책을 적용한다.
    """
    raise NotImplementedError("[SEC-018] 기능 구현이 필요합니다.")
