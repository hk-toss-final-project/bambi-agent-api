"""[WORKER-007] media Worker 스캐폴드."""

from infrastructure.messaging.base import JobMessage


async def run_media_worker(job: JobMessage) -> None:
    """[WORKER-007] 이미지와 시각 자료 생성 작업을 수행한다."""
    raise NotImplementedError("[WORKER-007] Worker 구현이 필요합니다.")
