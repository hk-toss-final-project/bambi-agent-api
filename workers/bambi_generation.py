"""[WORKER-003] bambi_generation Worker 스캐폴드."""

from infrastructure.messaging.base import JobMessage


# MVP: WORKER-003 Worker 범위에서 구현합니다.
async def run_bambi_generation_worker(job: JobMessage) -> None:
    """[WORKER-003] 개인 Wiki와 Global Source를 바탕으로 개인화 콘텐츠를 생성한다."""
    raise NotImplementedError("[WORKER-003] Worker 구현이 필요합니다.")
