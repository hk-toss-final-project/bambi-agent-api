"""Job Queue와 Integration Event Bus의 공통 메시지 계약."""

from dataclasses import dataclass, field
from typing import Mapping, Protocol


@dataclass(frozen=True, slots=True)
class JobMessage:
    """Worker가 소비하는 비동기 작업 메시지."""

    job_id: str
    job_type: str
    request_id: str
    user_id: str | None = None
    payload: Mapping[str, object] = field(default_factory=dict)


@dataclass(frozen=True, slots=True)
class EventMessage:
    """서비스 경계를 넘어 전달하는 Integration Event."""

    event_id: str
    event_type: str
    version: int
    payload: Mapping[str, object] = field(default_factory=dict)


class JobQueue(Protocol):
    """비동기 Agent 작업을 생산하고 소비하는 Queue 인터페이스."""

    async def enqueue(self, message: JobMessage) -> None:
        """작업 메시지를 해당 작업 유형의 Queue에 등록한다."""
        ...

    async def consume(self, queue_name: str) -> JobMessage:
        """지정 Queue에서 처리할 다음 작업 메시지를 가져온다."""
        ...


class EventBus(Protocol):
    """Integration Event를 외부 Consumer에 전달하는 인터페이스."""

    async def publish(self, event: EventMessage) -> None:
        """버전과 추적 정보가 포함된 이벤트를 발행한다."""
        ...
