"""기능 구현 모듈.

IMG-015, IMG-016 기능의 실제 구현 위치를 제공한다.
"""

from shared.contracts import FeatureRequest, FeatureResult


async def img_015(request: FeatureRequest) -> FeatureResult:
    """[IMG-015] 이미지 출처 관리.

    외부 이미지 사용 시 출처를 기록한다.
    """
    raise NotImplementedError("[IMG-015] 기능 구현이 필요합니다.")


async def img_016(request: FeatureRequest) -> FeatureResult:
    """[IMG-016] 이미지 라이선스 관리.

    이미지 사용 권한과 라이선스를 관리한다.
    """
    raise NotImplementedError("[IMG-016] 기능 구현이 필요합니다.")
