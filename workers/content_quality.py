"""[WORKER-004] content_quality Worker 스캐폴드."""

from infrastructure.messaging.base import JobMessage


async def run_content_quality_worker(job: JobMessage) -> None:
    """[WORKER-004] 생성 콘텐츠의 품질과 안전성을 평가한다."""
    raise NotImplementedError("[WORKER-004] Worker 구현이 필요합니다.")
