"""수집 스케줄 관리 라우트의 HTTP 계약을 검증한다.

Service가 호출하는 경로·상태코드·응답 형태를 실제 DB 없이 확인한다. 스케줄
서비스는 대역으로 바꾸고, 라우트가 올바른 인자로 호출하는지만 본다.
"""

from typing import Any, Iterator

import pytest
from fastapi.testclient import TestClient

from app.config import Settings
from app.dependencies import get_collection_schedule_service
from app.main import create_app
from tests.conftest import TEST_AUTHORIZATION_HEADER, TEST_INTERNAL_TOKEN
from app.schemas.collection_schedules import (
    CollectionKeywordRunResponse,
    CollectionProviderRunResponse,
    CollectionScheduleListResponse,
    CollectionScheduleRegisterRequest,
    CollectionScheduleResponse,
    CollectionScheduleRunResponse,
    CollectionScheduleUpdateRequest,
)

_PREFIX = "/internal/v1/collection-schedules"


def _response(source_key: str = "latest-naver", status: str = "active"):
    """테스트용 스케줄 응답 하나를 만든다."""
    return CollectionScheduleResponse(
        source_key=source_key,
        provider="naver",
        display_name="Latest naver",
        status=status,
        schedule_cron="0 */6 * * *",
        keywords=["코스피", "삼성전자"],
        language="ko",
        limit_per_provider=10,
        daily_max_runs=20,
        last_started_at=None,
        runs_today=0,
        next_run_at=None,
        cron_valid=True,
    )


class _FakeScheduleService:
    """호출 인자를 기록하는 수집 스케줄 서비스 대역."""

    def __init__(self) -> None:
        self.calls: list[tuple[str, Any]] = []

    async def list_schedules(
        self, *, source_key: str | None = None, history_limit: int = 20
    ) -> CollectionScheduleListResponse:
        """조회 인자를 기록하고 빈 이력과 스케줄 하나를 돌려준다."""
        self.calls.append(("list", (source_key, history_limit)))
        return CollectionScheduleListResponse(
            schedules=[_response()], recent_runs=[]
        )

    async def register(
        self, payload: CollectionScheduleRegisterRequest
    ) -> CollectionScheduleResponse:
        """등록 요청을 기록하고 저장 결과를 돌려준다."""
        self.calls.append(("register", payload))
        return _response(source_key=payload.source_key)

    async def update(
        self, source_key: str, payload: CollectionScheduleUpdateRequest
    ) -> CollectionScheduleResponse:
        """수정 요청을 기록하고 변경 결과를 돌려준다."""
        self.calls.append(("update", (source_key, payload)))
        return _response(source_key=source_key)

    async def pause(self, source_key: str) -> CollectionScheduleResponse:
        """중지 요청을 기록한다."""
        self.calls.append(("pause", source_key))
        return _response(source_key=source_key, status="paused")

    async def resume(self, source_key: str) -> CollectionScheduleResponse:
        """재개 요청을 기록한다."""
        self.calls.append(("resume", source_key))
        return _response(source_key=source_key, status="active")

    async def run_now(self, source_key: str) -> CollectionScheduleRunResponse:
        """즉시 실행 요청을 기록하고 수집 결과 하나를 돌려준다."""
        self.calls.append(("run_now", source_key))
        return CollectionScheduleRunResponse(
            source_key=source_key,
            provider="naver",
            status="completed",
            fetched_count=10,
            created_count=7,
            duplicate_count=3,
            keywords=[
                CollectionKeywordRunResponse(
                    keyword="코스피",
                    status="completed",
                    reason=None,
                    providers=[
                        CollectionProviderRunResponse(
                            provider="naver",
                            status="completed",
                            query="코스피",
                            run_id="run-1",
                            fetched_count=10,
                            created_count=7,
                            duplicate_count=3,
                        )
                    ],
                )
            ],
            schedule=_response(source_key=source_key),
        )


@pytest.fixture
def schedule_service() -> _FakeScheduleService:
    """라우트에 주입할 스케줄 서비스 대역을 반환한다."""
    return _FakeScheduleService()


@pytest.fixture
def schedule_client(
    schedule_service: _FakeScheduleService,
) -> Iterator[TestClient]:
    """스케줄 서비스 대역이 주입된 테스트 클라이언트를 제공한다."""
    application = create_app(
        Settings(environment="test", internal_api_token=TEST_INTERNAL_TOKEN)
    )
    application.dependency_overrides[get_collection_schedule_service] = (
        lambda: schedule_service
    )
    with TestClient(application) as client:
        client.headers.update(TEST_AUTHORIZATION_HEADER)
        yield client


def test_list_returns_schedules_and_runs(
    schedule_client: TestClient, schedule_service: _FakeScheduleService
) -> None:
    """목록 조회가 스케줄과 실행 이력을 함께 돌려주는지 검증한다."""
    response = schedule_client.get(_PREFIX, params={"history_limit": 5})

    assert response.status_code == 200
    body = response.json()
    assert body["schedules"][0]["source_key"] == "latest-naver"
    assert body["schedules"][0]["keywords"] == ["코스피", "삼성전자"]
    assert body["recent_runs"] == []
    assert schedule_service.calls[0] == ("list", (None, 5))


def test_register_returns_201(
    schedule_client: TestClient, schedule_service: _FakeScheduleService
) -> None:
    """스케줄 등록이 201과 저장된 설정을 돌려주는지 검증한다."""
    response = schedule_client.post(
        _PREFIX,
        json={
            "source_key": "latest-naver",
            "provider": "naver",
            "schedule_cron": "0 */6 * * *",
            "keywords": ["코스피", "삼성전자"],
            "daily_max_runs": 20,
        },
    )

    assert response.status_code == 201
    assert response.json()["status"] == "active"
    action, payload = schedule_service.calls[0]
    assert action == "register"
    assert payload.keywords == ["코스피", "삼성전자"]


def test_register_rejects_empty_keywords(schedule_client: TestClient) -> None:
    """키워드가 비면 스키마 단계에서 거부하는지 검증한다."""
    response = schedule_client.post(
        _PREFIX,
        json={
            "source_key": "latest-naver",
            "provider": "naver",
            "schedule_cron": "0 * * * *",
            "keywords": [],
        },
    )

    assert response.status_code == 422


def test_update_passes_only_given_fields(
    schedule_client: TestClient, schedule_service: _FakeScheduleService
) -> None:
    """부분 수정 요청에서 넘기지 않은 항목이 None으로 전달되는지 검증한다."""
    response = schedule_client.patch(
        f"{_PREFIX}/latest-naver", json={"schedule_cron": "0 * * * *"}
    )

    assert response.status_code == 200
    action, (source_key, payload) = schedule_service.calls[0]
    assert action == "update"
    assert source_key == "latest-naver"
    assert payload.schedule_cron == "0 * * * *"
    assert payload.keywords is None


def test_run_now_returns_collection_summary(
    schedule_client: TestClient, schedule_service: _FakeScheduleService
) -> None:
    """즉시 실행 라우트가 수집 합계와 키워드별 결과를 돌려주는지 검증한다."""
    response = schedule_client.post(f"{_PREFIX}/latest-naver/run")

    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "completed"
    assert body["created_count"] == 7
    assert body["keywords"][0]["providers"][0]["run_id"] == "run-1"
    assert body["schedule"]["source_key"] == "latest-naver"
    assert schedule_service.calls[0] == ("run_now", "latest-naver")


def test_pause_and_resume(
    schedule_client: TestClient, schedule_service: _FakeScheduleService
) -> None:
    """중지·재개 라우트가 상태를 바꿔 돌려주는지 검증한다."""
    paused = schedule_client.post(f"{_PREFIX}/latest-naver/pause")
    resumed = schedule_client.post(f"{_PREFIX}/latest-naver/resume")

    assert paused.json()["status"] == "paused"
    assert resumed.json()["status"] == "active"
    assert [call[0] for call in schedule_service.calls] == ["pause", "resume"]
