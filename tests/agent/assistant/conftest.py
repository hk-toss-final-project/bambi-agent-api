"""키워드 비서 테스트 공통 픽스처.

비서 이력 저장소는 기본적으로 환경변수(AGENT_DATABASE_URL)를 보고 PostgreSQL을
고르고, 없으면 저장소 루트의 `data/`에 JSON을 쓴다. 테스트가 그 둘 중 어느 쪽에도
닿으면 안 되므로(실제 DB 오염·실제 이력 파일 변경), 모든 비서 테스트를 임시
디렉터리 기반 JSON 저장소로 강제 격리한다.
"""

import pytest

from agent.assistant.features import storage


@pytest.fixture(autouse=True)
def isolate_assistant_storage(tmp_path):
    """비서 이력 저장소를 테스트별 임시 디렉터리로 격리한다."""
    storage.set_store(storage.JsonHistoryStore(tmp_path))
    yield tmp_path
    storage.set_store(None)
