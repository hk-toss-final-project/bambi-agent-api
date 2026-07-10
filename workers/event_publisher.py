"""[WORKER-012] event_publisher Worker 스캐폴드."""

from infrastructure.messaging.base import JobMessage


async def run_event_publisher_worker(job: JobMessage) -> None:
    """[WORKER-012] Outbox 이벤트를 Integration Event Bus로 발행한다."""
    raise NotImplementedError("[WORKER-012] Worker 구현이 필요합니다.")
