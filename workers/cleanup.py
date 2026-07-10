"""[WORKER-011] cleanup Worker 스캐폴드."""

from infrastructure.messaging.base import JobMessage


async def run_cleanup_worker(job: JobMessage) -> None:
    """[WORKER-011] 보존 기간이 만료된 데이터와 로그를 정리한다."""
    raise NotImplementedError("[WORKER-011] Worker 구현이 필요합니다.")
