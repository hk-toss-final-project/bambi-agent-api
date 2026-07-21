"""명세 기능 facade가 기존 런타임 구현을 실행하도록 연결하는 공통 도구.

기능별 ``api.py``는 import와 ``__all__``만 유지하고, ``features/``의 실제
기능 함수가 주입된 구현을 실행해 ``FeatureResult``로 정규화할 때 사용한다.
"""

from collections.abc import Awaitable, Callable, Mapping
from inspect import isawaitable
from typing import TypeAlias, cast

from shared.contracts import FeatureRequest, FeatureResult

FeatureImplementation: TypeAlias = Callable[
    [], object | Awaitable[object]
]


def require_feature_implementation(
    request: FeatureRequest,
    *,
    feature_id: str,
) -> FeatureImplementation:
    """요청 Payload에서 실행할 실제 기능 구현을 검증해 반환한다."""
    implementation = request.payload.get("implementation")
    if not callable(implementation):
        raise ValueError(f"{feature_id}에 실행할 implementation이 필요합니다.")
    return cast(FeatureImplementation, implementation)


async def execute_feature_implementation(
    request: FeatureRequest,
    *,
    feature_id: str,
) -> FeatureResult:
    """주입된 동기·비동기 구현을 실행하고 공통 기능 결과로 변환한다."""
    implementation = require_feature_implementation(request, feature_id=feature_id)
    value = implementation()
    if isawaitable(value):
        value = await value
    if isinstance(value, FeatureResult):
        if value.feature_id != feature_id:
            raise ValueError(
                f"{feature_id} 구현이 다른 기능 결과를 반환했습니다: "
                f"{value.feature_id}"
            )
        return value
    if isinstance(value, Mapping):
        return FeatureResult(feature_id=feature_id, data=dict(value))
    return FeatureResult(feature_id=feature_id, data={"result": value})
