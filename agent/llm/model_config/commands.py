"""기능 구현 모듈.

MODEL-001, MODEL-003, MODEL-004 기능의 실제 구현 위치를 제공한다.
"""

from shared.contracts import FeatureRequest, FeatureResult


async def model_001(request: FeatureRequest) -> FeatureResult:
    """[MODEL-001] Model Config 생성.

    모델 실행 설정을 생성한다.
    """
    raise NotImplementedError("[MODEL-001] 기능 구현이 필요합니다.")


async def model_003(request: FeatureRequest) -> FeatureResult:
    """[MODEL-003] Model Config 수정.

    모델 파라미터와 실행 정책을 수정한다.
    """
    raise NotImplementedError("[MODEL-003] 기능 구현이 필요합니다.")


async def model_004(request: FeatureRequest) -> FeatureResult:
    """[MODEL-004] Model Config 삭제.

    사용하지 않는 설정을 비활성화한다.
    """
    raise NotImplementedError("[MODEL-004] 기능 구현이 필요합니다.")
