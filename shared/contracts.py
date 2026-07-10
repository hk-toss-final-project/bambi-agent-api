"""기능 스캐폴드가 공통으로 사용하는 요청과 결과 계약.

상세 API 스키마가 확정되기 전까지 계층 간 함수 시그니처를 일관되게 유지한다.
"""

from dataclasses import dataclass, field
from typing import Mapping


@dataclass(frozen=True, slots=True)
class FeatureRequest:
    """명세 기능 함수에 전달되는 최소 공통 요청 컨텍스트."""

    request_id: str
    actor_id: str | None = None
    user_id: str | None = None
    payload: Mapping[str, object] = field(default_factory=dict)


@dataclass(frozen=True, slots=True)
class FeatureResult:
    """명세 기능 함수가 반환하는 최소 공통 결과 컨텍스트."""

    feature_id: str
    data: Mapping[str, object] = field(default_factory=dict)
