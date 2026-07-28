"""수집 스케줄 관리 애플리케이션 서비스.

Service API 라우트와 Scheduler 기능(SCH-017·018·019·020·022) 사이에서 DB 연결
수명과 오류 변환을 담당한다. 기능 로직은 `scheduler.api` facade가 소유하고, 이
서비스는 연결을 빌려 주고 결과를 HTTP 응답 모델로 옮기는 일만 한다.
"""

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from typing import Any, Protocol

from fastapi import status
from psycopg import AsyncConnection

from app.exceptions import AgentApiError, ErrorDetail
from app.schemas.collection_schedules import (
    CollectionRunResponse,
    CollectionScheduleListResponse,
    CollectionScheduleRegisterRequest,
    CollectionScheduleResponse,
    CollectionScheduleUpdateRequest,
)
from infrastructure.persistence.api import GlobalCollectionRunRecord
from scheduler.api import (
    CollectionScheduleView,
    UnknownCollectionScheduleError,
    sch_017,
    sch_018,
    sch_019,
    sch_020,
    sch_022,
)

type DictRow = dict[str, Any]


class ConnectionProvider(Protocol):
    """Agent DB 연결을 빌려주는 저장소 계약."""

    def acquire_connection(
        self,
    ) -> Any:  # pragma: no cover - Protocol 선언
        """Pool에서 연결 하나를 빌려주는 async context manager를 반환한다."""
        ...


def _to_response(view: CollectionScheduleView) -> CollectionScheduleResponse:
    """스케줄 상태 값 객체를 HTTP 응답 모델로 옮긴다."""
    return CollectionScheduleResponse(
        source_key=view.source_key,
        provider=view.provider,
        display_name=view.display_name,
        status=view.status,
        schedule_cron=view.schedule_cron,
        keywords=list(view.keywords),
        language=view.language,
        limit_per_provider=view.limit_per_provider,
        daily_max_runs=view.daily_max_runs,
        last_started_at=view.last_started_at,
        runs_today=view.runs_today,
        next_run_at=view.next_run_at,
        cron_valid=view.cron_valid,
    )


def _to_run_response(record: GlobalCollectionRunRecord) -> CollectionRunResponse:
    """수집 실행 이력을 HTTP 응답 모델로 옮긴다."""
    return CollectionRunResponse(
        run_id=record.run_id,
        source_key=record.source_key,
        query=record.query,
        status=record.status,
        fetched_count=record.fetched_count,
        created_count=record.created_count,
        duplicate_count=record.duplicate_count,
        failed_count=record.failed_count,
        error_code=record.error_code,
        started_at=record.started_at,
        completed_at=record.completed_at,
    )


def _not_found(source_key: str) -> AgentApiError:
    """등록되지 않은 source_key 요청을 404로 변환한다."""
    return AgentApiError(
        status.HTTP_404_NOT_FOUND,
        ErrorDetail(
            code="COLLECTION_SCHEDULE_NOT_FOUND",
            message=f"수집 스케줄을 찾을 수 없습니다: {source_key}",
        ),
    )


def _invalid(message: str) -> AgentApiError:
    """검증에 실패한 스케줄 설정을 422로 변환한다."""
    return AgentApiError(
        status.HTTP_422_UNPROCESSABLE_CONTENT,
        ErrorDetail(code="REQUEST_VALIDATION_ERROR", message=message),
    )


class CollectionScheduleService:
    """Service API의 수집 스케줄 조회·등록·수정·중지·재개를 처리한다."""

    def __init__(self, repository: ConnectionProvider) -> None:
        """연결을 빌려줄 저장소를 주입받는다."""
        self._repository = repository

    @asynccontextmanager
    async def _connection(self) -> AsyncIterator[AsyncConnection[DictRow]]:
        """저장소 Pool에서 연결 하나를 빌린다."""
        async with self._repository.acquire_connection() as connection:
            yield connection

    async def list_schedules(
        self, *, source_key: str | None = None, history_limit: int = 20
    ) -> CollectionScheduleListResponse:
        """[SCH-022] 등록된 수집 스케줄과 최근 실행 이력을 반환한다."""
        async with self._connection() as connection:
            try:
                schedules, runs = await sch_022(
                    connection,
                    source_key=source_key,
                    history_limit=history_limit,
                )
            except UnknownCollectionScheduleError as error:
                raise _not_found(error.source_key) from error
        return CollectionScheduleListResponse(
            schedules=[_to_response(view) for view in schedules],
            recent_runs=[_to_run_response(record) for record in runs],
        )

    async def register(
        self, payload: CollectionScheduleRegisterRequest
    ) -> CollectionScheduleResponse:
        """[SCH-017] 수집 스케줄을 등록하거나 같은 Key의 설정을 덮어쓴다."""
        async with self._connection() as connection:
            try:
                async with connection.transaction():
                    view = await sch_017(
                        connection,
                        source_key=payload.source_key,
                        provider=payload.provider,
                        schedule_cron=payload.schedule_cron,
                        keywords=payload.keywords,
                        display_name=payload.display_name,
                        language=payload.language,
                        limit_per_provider=payload.limit_per_provider,
                        daily_max_runs=payload.daily_max_runs,
                    )
            except ValueError as error:
                raise _invalid(str(error)) from error
        return _to_response(view)

    async def update(
        self, source_key: str, payload: CollectionScheduleUpdateRequest
    ) -> CollectionScheduleResponse:
        """[SCH-018] 등록된 수집 스케줄의 지정한 항목만 변경한다."""
        async with self._connection() as connection:
            try:
                async with connection.transaction():
                    view = await sch_018(
                        connection,
                        source_key=source_key,
                        schedule_cron=payload.schedule_cron,
                        keywords=payload.keywords,
                        language=payload.language,
                        limit_per_provider=payload.limit_per_provider,
                        daily_max_runs=payload.daily_max_runs,
                    )
            except UnknownCollectionScheduleError as error:
                raise _not_found(error.source_key) from error
            except ValueError as error:
                raise _invalid(str(error)) from error
        return _to_response(view)

    async def pause(self, source_key: str) -> CollectionScheduleResponse:
        """[SCH-019] 수집 스케줄 실행을 일시 중지한다."""
        return await self._set_status(source_key, resume=False)

    async def resume(self, source_key: str) -> CollectionScheduleResponse:
        """[SCH-020] 중지된 수집 스케줄을 다시 활성화한다."""
        return await self._set_status(source_key, resume=True)

    async def _set_status(
        self, source_key: str, *, resume: bool
    ) -> CollectionScheduleResponse:
        """중지·재개 기능을 호출하고 결과를 응답 모델로 옮긴다."""
        feature = sch_020 if resume else sch_019
        async with self._connection() as connection:
            try:
                async with connection.transaction():
                    view = await feature(connection, source_key=source_key)
            except UnknownCollectionScheduleError as error:
                raise _not_found(error.source_key) from error
        return _to_response(view)
