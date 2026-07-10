"""[WORKER-009] embedding Worker 스캐폴드."""

from infrastructure.messaging.base import JobMessage


async def run_embedding_worker(job: JobMessage) -> None:
    """[WORKER-009] 문서와 Chunk의 Embedding을 생성한다."""
    raise NotImplementedError("[WORKER-009] Worker 구현이 필요합니다.")
