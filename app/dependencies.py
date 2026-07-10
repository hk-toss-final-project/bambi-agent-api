"""FastAPI 라우터에서 사용할 공통 의존성 계약.

DB, Queue, Provider와 Agent 그래프 인스턴스의 주입 경계를 정의한다.
"""

from dataclasses import dataclass

from app.config import Settings


@dataclass(frozen=True, slots=True)
class AppContainer:
    """API 요청 처리에 필요한 애플리케이션 컴포넌트 모음."""

    settings: Settings
    database: object | None = None
    vector_store: object | None = None
    queue: object | None = None
    event_bus: object | None = None
    llm_provider: object | None = None
    embedding_provider: object | None = None


def get_container() -> AppContainer:
    """현재 애플리케이션 컨테이너를 FastAPI 의존성으로 제공한다."""
    raise NotImplementedError("애플리케이션 의존성 주입 구현이 필요합니다.")
