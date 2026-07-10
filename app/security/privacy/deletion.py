"""기능 구현 모듈.

SEC-014, SEC-015, SEC-016, SEC-017 기능의 실제 구현 위치를 제공한다.
"""

from shared.contracts import FeatureRequest, FeatureResult


async def sec_014(request: FeatureRequest) -> FeatureResult:
    """[SEC-014] 사용자 삭제 요청 반영.

    탈퇴와 삭제 요청을 Agent 데이터에 반영한다.
    """
    raise NotImplementedError("[SEC-014] 기능 구현이 필요합니다.")


async def sec_015(request: FeatureRequest) -> FeatureResult:
    """[SEC-015] Wiki 삭제 전파.

    개인 Wiki 문서와 버전을 삭제하거나 비활성화한다.
    """
    raise NotImplementedError("[SEC-015] 기능 구현이 필요합니다.")


async def sec_016(request: FeatureRequest) -> FeatureResult:
    """[SEC-016] Embedding 삭제 전파.

    삭제된 문서의 Vector 데이터를 제거한다.
    """
    raise NotImplementedError("[SEC-016] 기능 구현이 필요합니다.")


async def sec_017(request: FeatureRequest) -> FeatureResult:
    """[SEC-017] Cache 삭제 전파.

    삭제된 사용자 데이터의 Cache를 제거한다.
    """
    raise NotImplementedError("[SEC-017] 기능 구현이 필요합니다.")
