"""[WORKER-001] global_source_collector Worker 스캐폴드."""

from infrastructure.messaging.base import JobMessage


# MVP: WORKER-001 Worker 범위에서 구현합니다.
async def run_global_source_collector_worker(job: JobMessage) -> None:
    """[WORKER-001] 외부 데이터를 수집하고 Global Source Pool에 저장한다."""
    raise NotImplementedError("[WORKER-001] Worker 구현이 필요합니다.")
