"""[WORKER-002] personal_wiki_builder Worker 스캐폴드."""

from infrastructure.messaging.base import JobMessage


# MVP: WORKER-002 Worker 범위에서 구현합니다.
async def run_personal_wiki_builder_worker(job: JobMessage) -> None:
    """[WORKER-002] 사용자 선택 데이터를 개인 Wiki로 구성한다."""
    raise NotImplementedError("[WORKER-002] Worker 구현이 필요합니다.")
