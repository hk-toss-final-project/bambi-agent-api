"""기능 구현 모듈.

NFR-020 기능의 실제 구현 위치를 제공한다.
"""

from shared.contracts import FeatureRequest, FeatureResult


async def nfr_020(request: FeatureRequest) -> FeatureResult:
    """[NFR-020] 사용자별 데이터 격리.

    모든 개인 데이터 조회에 사용자 범위를 강제한다.
    """
    raise NotImplementedError("[NFR-020] 기능 구현이 필요합니다.")
