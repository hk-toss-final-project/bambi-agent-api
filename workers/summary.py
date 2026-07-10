"""[WORKER-005] summary Worker 스캐폴드."""

from infrastructure.messaging.base import JobMessage


async def run_summary_worker(job: JobMessage) -> None:
    """[WORKER-005] 문서와 콘텐츠의 요약 작업을 수행한다."""
    raise NotImplementedError("[WORKER-005] Worker 구현이 필요합니다.")
