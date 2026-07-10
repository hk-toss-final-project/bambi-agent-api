"""[WORKER-006] translation Worker 스캐폴드."""

from infrastructure.messaging.base import JobMessage


async def run_translation_worker(job: JobMessage) -> None:
    """[WORKER-006] 콘텐츠 번역 작업을 수행한다."""
    raise NotImplementedError("[WORKER-006] Worker 구현이 필요합니다.")
