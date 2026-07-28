"""키워드 비서 기능 영역의 공개 facade.

구현 모듈(features/)의 기능 함수를 안정적인 import 경로로 다시 노출한다.
외부 계층(app/assistant/web.py 등)은 features/ 구현 파일을 직접 참조하지 않고
이 모듈만 import한다.

이 기능 영역은 전체 명세(docs/agent-api-feature-spec.md)의 1~43절 기능 ID
체계(REPORT-*, WBA-* 등)에 속하지 않는 별도 제품 라인이라, 기능-ID 형식
함수(`async def xxx_001(request) -> FeatureResult`)를 두지 않는다. 대신
AGENTS.md의 구조 규칙(구현은 features/, 공개는 api.py)은 그대로 따른다.
"""

from .features.config import collect_window_days
from .features.feeds import clean_article_body
from .features.topic_intent import resolve_topic_intent
from .features.graph import build_graph as build_assistant_graph
from .features.service import assist_daily_agent

__all__ = [
    "assist_daily_agent",
    "build_assistant_graph",
    "clean_article_body",
    "collect_window_days",
    "resolve_topic_intent",
]
