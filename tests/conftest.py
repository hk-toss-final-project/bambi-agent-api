"""테스트 전반에서 재사용하는 결정적 공통 픽스처."""

import pytest

from shared.contracts import FeatureRequest


@pytest.fixture
def feature_request() -> FeatureRequest:
    """외부 호출 없이 사용할 수 있는 공통 기능 요청을 반환한다."""
    return FeatureRequest(request_id="test-request", actor_id="test-service")
