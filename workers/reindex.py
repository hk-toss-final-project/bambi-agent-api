"""[WORKER-010] reindex Worker 스캐폴드."""

from infrastructure.messaging.base import JobMessage


async def run_reindex_worker(job: JobMessage) -> None:
    """[WORKER-010] Embedding 모델 변경에 따라 Vector를 재색인한다."""
    raise NotImplementedError("[WORKER-010] Worker 구현이 필요합니다.")
