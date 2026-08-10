"""온보딩 Topic 컨텍스트와 사용자 키워드 캐시 PostgreSQL 경계를 검증한다."""

import asyncio
from typing import Any

from infrastructure.persistence.features.onboarding_contexts import (
    list_cached_custom_topic_contexts,
    list_onboarding_topic_contexts,
    save_custom_topic_contexts,
)
from shared.onboarding_context_models import OnboardingTopicContext


class _Cursor:
    """지정한 Row 목록을 반환하는 Cursor 대역."""

    def __init__(self, rows: list[dict[str, Any]]) -> None:
        self.rows = rows

    async def fetchall(self) -> list[dict[str, Any]]:
        """전체 Row를 반환한다."""
        return self.rows

    async def fetchone(self) -> dict[str, Any] | None:
        """첫 Row 또는 None을 반환한다."""
        return self.rows[0] if self.rows else None


class _Connection:
    """SQL과 Parameter, 호출별 반환 Row를 기록하는 연결 대역."""

    def __init__(self, results: list[list[dict[str, Any]]]) -> None:
        self.results = list(results)
        self.executed: list[tuple[str, tuple[Any, ...]]] = []

    async def execute(self, query: str, params: tuple[Any, ...]) -> _Cursor:
        """SQL을 기록하고 다음 Cursor 결과를 반환한다."""
        self.executed.append((query, params))
        return _Cursor(self.results.pop(0) if self.results else [])


def test_list_onboarding_topic_contexts_maps_structured_seed() -> None:
    """정식 Topic JSON 배열과 버전 정보를 공유 값 객체로 변환한다."""
    connection = _Connection(
        [
            [
                {
                    "taxonomy_version": "1.0.0-draft",
                    "topic_id": "ai_ml",
                    "locale": "ko-KR",
                    "canonical_name": "AI·머신러닝",
                    "node_kind": "concept",
                    "subtype": "field",
                    "definition": "인공지능 기술 분야다.",
                    "key_characteristics": ["학습", "추론"],
                    "applications": ["자동화"],
                    "aliases": ["AI"],
                    "related_topic_ids": ["programming"],
                    "content_version": 1,
                    "taxonomy_name": "AI·머신러닝",
                    "taxonomy_name_en": "AI & Machine Learning",
                    "taxonomy_keywords": ["생성형 AI", "LLM"],
                }
            ]
        ]
    )

    contexts = asyncio.run(
        list_onboarding_topic_contexts(
            connection,  # type: ignore[arg-type]
            taxonomy_version="1.0.0-draft",
            locale="ko-KR",
        )
    )

    assert contexts[0].topic_id == "ai_ml"
    assert contexts[0].key_characteristics == ("학습", "추론")
    assert "LLM" in contexts[0].aliases
    assert contexts[0].resolution_kind == "deterministic_topic"
    assert connection.executed[0][1] == ("1.0.0-draft", "ko-KR")


def test_list_cached_contexts_normalizes_keyword_lookup() -> None:
    """사용자 입력의 공백·대소문자를 정규화해 active 캐시만 조회한다."""
    connection = _Connection(
        [
            [
                {
                    "original_keyword": "Project Bambi",
                    "normalized_keyword": "project bambi",
                    "locale": "ko",
                    "context_signature": "a" * 64,
                    "canonical_name": "Project Bambi",
                    "node_kind": "entity",
                    "subtype": "project",
                    "definition": "동명 프로젝트를 탐색하기 위한 항목이다.",
                    "key_characteristics": [],
                    "applications": ["자료 연결"],
                    "aliases": [],
                    "search_terms": ["Project Bambi"],
                    "possible_meanings": ["동명 프로젝트"],
                    "resolution_kind": "llm_generated",
                    "confidence": 0.7,
                    "model_name": "test-model",
                    "prompt_version": "v1",
                    "metadata": {},
                }
            ]
        ]
    )

    contexts = asyncio.run(
        list_cached_custom_topic_contexts(
            connection,  # type: ignore[arg-type]
            user_id="user-1",
            keywords=["  PROJECT   Bambi "],
            locale="ko",
        )
    )

    assert contexts[0].canonical_name == "Project Bambi"
    assert contexts[0].context_signature == "a" * 64
    assert connection.executed[0][1] == ("user-1", ["project bambi"], "ko")


def test_save_custom_context_supersedes_old_signature_and_upserts() -> None:
    """새 Prompt 서명은 과거 active 캐시를 대체하고 구조화 필드를 저장한다."""
    connection = _Connection([[], [{"id": "context-1"}]])
    context = OnboardingTopicContext(
        original_keyword="양자 센서",
        canonical_name="양자 센서",
        node_kind="concept",
        subtype="field",
        definition="양자 효과를 이용하는 정밀 센서 분야다.",
        key_characteristics=("정밀 측정",),
        applications=("계측",),
        search_terms=("quantum sensing",),
        possible_meanings=(),
        locale="ko",
        resolution_kind="llm_generated",
        confidence=0.9,
        context_signature="b" * 64,
        model_name="test-model",
        prompt_version="v1",
    )

    count = asyncio.run(
        save_custom_topic_contexts(
            connection,  # type: ignore[arg-type]
            user_id="user-1",
            contexts=[context],
        )
    )

    assert count == 1
    assert "status = 'superseded'" in connection.executed[0][0]
    insert_query, insert_params = connection.executed[1]
    assert "ON CONFLICT" in insert_query
    assert insert_params[2] == "양자 센서"
    assert insert_params[9].obj == ["정밀 측정"]
