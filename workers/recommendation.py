"""[WORKER-008] recommendation Worker 스캐폴드."""

from infrastructure.messaging.base import JobMessage


async def run_recommendation_worker(job: JobMessage) -> None:
    """[WORKER-008] 사용자별 추천 후보를 생성한다."""
    raise NotImplementedError("[WORKER-008] Worker 구현이 필요합니다.")
