"""기능 구현 모듈.

KEY-009, KEY-014 기능의 실제 구현 위치를 제공한다.
"""

from shared.contracts import FeatureRequest, FeatureResult


async def key_009(request: FeatureRequest) -> FeatureResult:
    """[KEY-009] API Key Scope 설정.

    Key로 사용할 수 있는 기능 범위를 설정한다.
    """
    raise NotImplementedError("[KEY-009] 기능 구현이 필요합니다.")


async def key_014(request: FeatureRequest) -> FeatureResult:
    """[KEY-014] Personal Wiki 접근 권한.

    특정 사용자의 Wiki에 접근할 수 있는 권한을 연결한다.
    """
    raise NotImplementedError("[KEY-014] 기능 구현이 필요합니다.")
