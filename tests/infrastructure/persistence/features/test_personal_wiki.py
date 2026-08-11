"""infrastructure/persistence/features/personal_wiki.py의 순수 조회 함수를 검증한다."""

import asyncio
import hashlib
from datetime import UTC, date, datetime
from typing import Any

import pytest

from agent.wiki_builder.models import (
    GeneratedArtifact,
    WikiBuildPlan,
    WikiDocumentPlan,
    WikiRelationPlan,
)
from infrastructure.persistence.features.personal_wiki import (
    RegisteredUrlSource,
    SavedUserSourceVersion,
    UserSourceDocumentForAgent,
    _observed_relations_for_build,
    _relation_persistence_values,
    _count_wiki_relations,
    _upsert_wiki_document,
    chunk_wiki_markdown,
    get_user_source_document_version_for_agent,
    list_existing_wiki_entries,
    list_existing_wiki_relations,
    list_onboarding_wiki_anchor_keys,
    list_related_wiki_keywords,
    list_wiki_graph_relation_snapshot,
    list_wiki_node_embeddings,
    list_user_source_versions_for_rebuild,
    mark_url_source_event,
    register_user_url_source,
    save_user_url_document_version,
    sync_wiki_relation_supports,
    supersede_personal_wiki_for_rebuild,
    update_full_wiki_rebuild_summary,
)


def test_list_wiki_node_embeddings_averages_current_chunk_vectors() -> None:
    """현재 노드의 여러 Chunk Vector를 차원별로 평균한다."""
    connection = _FakeConnection(
        [
            {
                "document_kind": "concept",
                "document_key": "weather",
                "embedding": "[1,0,0]",
            },
            {
                "document_kind": "concept",
                "document_key": "weather",
                "embedding": "[0,1,0]",
            },
            {
                "document_kind": "entity",
                "document_key": "seoul",
                "embedding": "손상",
            },
        ]
    )

    result = asyncio.run(
        list_wiki_node_embeddings(
            connection,  # type: ignore[arg-type]
            namespace_key="user/56",
            model_name="text-embedding-3-small",
        )
    )

    assert len(result) == 1
    assert result[0].document_key == "weather"
    assert result[0].embedding == (0.5, 0.5, 0.0)
    query, params = connection.executed[0]
    assert "embedding.embedding::text" in query
    assert "version.version = document.current_version" in query
    assert "document.status = 'active'" in query
    assert params == ("text-embedding-3-small", "user/56")


def test_list_onboarding_wiki_anchor_keys_uses_source_provenance() -> None:
    """온보딩 anchor를 제목 추측이 아닌 원본 source_type으로 조회한다."""
    connection = _FakeConnection(
        [{"document_kind": "concept", "document_key": "weather"}]
    )

    result = asyncio.run(
        list_onboarding_wiki_anchor_keys(
            connection,  # type: ignore[arg-type]
            namespace_key="user/56",
        )
    )

    assert result == [("concept", "weather")]
    query, params = connection.executed[0]
    assert "source_document.source_type = 'onboarding_seed'" in query
    assert params == ("user/56",)


def test_list_user_source_versions_for_rebuild_reads_current_versions() -> None:
    """재구성 원본은 삭제되지 않은 Head의 현재 Version으로 고정한다."""
    connection = _FakeConnection(_sample_row())

    result = asyncio.run(
        list_user_source_versions_for_rebuild(
            connection,  # type: ignore[arg-type]
            user_id="user-1",
        )
    )

    assert len(result) == 1
    assert result[0].source_document_version_id == "version-1"
    query, params = connection.executed[0]
    assert "version.version = document.current_version" in query
    assert "document.deleted_at IS NULL" in query
    assert "document.source_type = 'onboarding_seed' THEN 0" in query
    assert "document.created_at" in query
    assert params == ("user-1", "user/user-1")


def test_supersede_personal_wiki_for_rebuild_clears_retry_snapshot_atomically() -> None:
    """재시도 Snapshot을 비우고 관계 근거·Head·문서를 대체 상태로 만든다."""
    connection = _FakeConnection([{"id": "doc-1"}, {"id": "doc-2"}])

    count = asyncio.run(
        supersede_personal_wiki_for_rebuild(
            connection,  # type: ignore[arg-type]
            user_id="user-1",
            job_id="job-1",
        )
    )

    assert count == 2
    queries = [query for query, _params in connection.executed]
    assert "DELETE FROM agent.wiki_version_documents" in queries[0]
    assert "UPDATE agent.wiki_relation_supports" in queries[1]
    assert "UPDATE agent.wiki_document_relations" in queries[2]
    assert "UPDATE agent.wiki_documents" in queries[3]
    assert connection.executed[0][1] == ("user-1", "job-1")


def test_update_full_wiki_rebuild_summary_records_complete_replacement_scope() -> None:
    """Full Rebuild Build Head에 전체 원본·문서 교체 범위를 기록한다."""
    connection = _FakeConnection(None)

    asyncio.run(
        update_full_wiki_rebuild_summary(
            connection,  # type: ignore[arg-type]
            user_id="user-1",
            wiki_version_id="wiki-1",
            source_count=4,
            affected_document_count=9,
            superseded_document_count=7,
        )
    )

    query, params = connection.executed[0]
    assert "UPDATE agent.wiki_versions" in query
    assert params[0].obj == {
        "mode": "full_rebuild",
        "source_count": 4,
        "affected_document_count": 9,
        "superseded_document_count": 7,
    }
    assert params[1:] == ("wiki-1", "user-1", "user/user-1")


def test_update_full_wiki_rebuild_summary_includes_quality_metrics_when_given() -> None:
    """WBA-014 품질 지표를 넘기면 같은 Snapshot에 함께 기록해 추이를 남긴다."""
    connection = _FakeConnection(None)

    asyncio.run(
        update_full_wiki_rebuild_summary(
            connection,  # type: ignore[arg-type]
            user_id="user-1",
            wiki_version_id="wiki-1",
            source_count=4,
            affected_document_count=9,
            superseded_document_count=7,
            quality_metrics={"orphan_count": 2, "duplicate_surface_count": 0},
        )
    )

    _query, params = connection.executed[0]
    assert params[0].obj["quality_metrics"] == {
        "orphan_count": 2,
        "duplicate_surface_count": 0,
    }


def test_update_full_wiki_rebuild_summary_omits_quality_metrics_key_when_not_given() -> None:
    """quality_metrics를 안 넘기면 기존 요약 구조를 그대로 유지한다."""
    connection = _FakeConnection(None)

    asyncio.run(
        update_full_wiki_rebuild_summary(
            connection,  # type: ignore[arg-type]
            user_id="user-1",
            wiki_version_id="wiki-1",
            source_count=1,
            affected_document_count=1,
            superseded_document_count=0,
        )
    )

    _query, params = connection.executed[0]
    assert "quality_metrics" not in params[0].obj


class _FakeCursor:
    """psycopg Cursor의 fetchone만 흉내 내는 결정적 Test Double."""

    def __init__(self, row: dict[str, Any] | list[dict[str, Any]] | None) -> None:
        """조회 시 반환할 고정 Row를 보관한다."""
        self._row = row

    async def fetchone(self) -> dict[str, Any] | None:
        """생성 시 전달된 고정 Row를 그대로 반환한다."""
        if isinstance(self._row, list):
            return self._row[0] if self._row else None
        return self._row

    async def fetchall(self) -> list[dict[str, Any]]:
        """생성 시 전달된 Row를 목록으로 반환한다."""
        if self._row is None:
            return []
        return self._row if isinstance(self._row, list) else [self._row]


class _FakeConnection:
    """전달된 SQL과 Parameter를 기록하고 고정된 Row를 반환하는 Test Double."""

    def __init__(self, row: dict[str, Any] | list[dict[str, Any]] | None) -> None:
        """고정 Row와 빈 SQL 실행 내역을 초기화한다."""
        self._row = row
        self.executed: list[tuple[str, tuple[Any, ...]]] = []

    async def execute(self, query: str, params: tuple[Any, ...]) -> _FakeCursor:
        """실행된 SQL과 Parameter를 기록한 뒤 고정된 Cursor를 반환한다."""
        self.executed.append((query, params))
        return _FakeCursor(self._row)


def test_count_wiki_relations_scopes_query_to_namespace() -> None:
    """저장 관계 수를 사용자 Namespace 범위로 조회한다."""
    connection = _FakeConnection({"relation_count": 4})

    count = asyncio.run(
        _count_wiki_relations(
            connection,  # type: ignore[arg-type]
            namespace_key="user/user-1",
        )
    )

    assert count == 4
    query, params = connection.executed[0]
    assert "FROM agent.wiki_document_relations AS relation" in query
    assert "relation.status = 'active'" in query
    assert "relation.review_status <> 'rejected'" in query
    assert "source.deleted_at IS NULL" in query
    assert "target.deleted_at IS NULL" in query
    assert params == ("user/user-1",)


def _sample_row() -> dict[str, Any]:
    """user_source_document_versions와 user_source_documents를 결합한 예시 Row."""
    return {
        "source_document_id": "doc-1",
        "user_id": "user-1",
        "namespace_key": "user/user-1",
        "source_type": "web_clipping",
        "canonical_url": "https://example.com/article",
        "source_document_version_id": "version-1",
        "source_event_id": "event-1",
        "version": 2,
        "title": "제목",
        "author": "저자",
        "published_at": datetime(2026, 7, 1, tzinfo=UTC),
        "clipped_on": date(2026, 7, 2),
        "description": "설명",
        "tags": ["ai", "wiki"],
        "raw_content": "# 본문",
        "content_format": "markdown",
        "content_hash": "a" * 64,
        "object_uri": None,
        "source_metadata": {"clipper": "obsidian"},
    }


def test_get_user_source_document_version_for_agent_maps_row() -> None:
    """조회된 Row를 Agent가 바로 사용할 UserSourceDocumentForAgent로 변환하는지 검증한다."""
    connection = _FakeConnection(_sample_row())

    result = asyncio.run(
        get_user_source_document_version_for_agent(
            connection,  # type: ignore[arg-type]
            user_id="user-1",
            source_document_version_id="version-1",
        )
    )

    assert result == UserSourceDocumentForAgent(
        source_document_id="doc-1",
        source_document_version_id="version-1",
        source_event_id="event-1",
        user_id="user-1",
        namespace_key="user/user-1",
        source_type="web_clipping",
        canonical_url="https://example.com/article",
        version=2,
        title="제목",
        author="저자",
        published_at=datetime(2026, 7, 1, tzinfo=UTC),
        clipped_on=date(2026, 7, 2),
        description="설명",
        tags=["ai", "wiki"],
        raw_content="# 본문",
        content_format="markdown",
        content_hash="a" * 64,
        object_uri=None,
            source_metadata={"clipper": "obsidian"},
            head_current_version=2,
        )
    query, params = connection.executed[0]
    assert "agent.user_source_document_versions" in query
    assert "agent.user_source_documents" in query
    assert params == ("version-1", "user-1")


def test_get_user_source_document_version_for_agent_returns_none_when_missing() -> None:
    """일치하는 Row가 없으면 None을 반환하는지 검증한다."""
    connection = _FakeConnection(None)

    result = asyncio.run(
        get_user_source_document_version_for_agent(
            connection,  # type: ignore[arg-type]
            user_id="user-1",
            source_document_version_id="missing-version",
        )
    )

    assert result is None


def test_get_user_source_document_version_for_agent_defaults_null_collections() -> None:
    """tags와 source_metadata가 NULL로 조회돼도 빈 컬렉션으로 채워지는지 검증한다."""
    row = _sample_row()
    row["tags"] = None
    row["source_metadata"] = None
    connection = _FakeConnection(row)

    result = asyncio.run(
        get_user_source_document_version_for_agent(
            connection,  # type: ignore[arg-type]
            user_id="user-1",
            source_document_version_id="version-1",
        )
    )

    assert result is not None
    assert result.tags == []
    assert result.source_metadata == {}


def test_list_existing_wiki_entries_maps_current_versions() -> None:
    """기존 Wiki 최신 Version과 Builder Metadata를 중복 판단 객체로 변환한다."""
    connection = _FakeConnection(
        [
            {
                "document_kind": "entity",
                "document_key": "obsidian",
                "domain": "product",
                "title": "Obsidian",
                "summary": "Markdown 노트 도구",
                "source_metadata": {"aliases": ["옵시디언"]},
            }
        ]
    )

    result = asyncio.run(
        list_existing_wiki_entries(
            connection,  # type: ignore[arg-type]
            user_id="user-1",
            document_kind="entity",
        )
    )

    assert result[0].document_key == "obsidian"
    assert result[0].metadata == {"aliases": ["옵시디언"]}
    query, params = connection.executed[0]
    assert "version.version = document.current_version" in query
    assert params == ("user/user-1", "entity")


def test_chunk_wiki_markdown_splits_at_heading_boundaries() -> None:
    """Wiki Markdown을 섹션 Heading 단위의 검색 Chunk로 나눈다."""
    content = "---\ntype: entity\n---\n## Description\n설명\n## Related Entities\n- 관계"

    chunks = chunk_wiki_markdown(content)

    assert chunks == [
        "---\ntype: entity\n---",
        "## Description\n설명",
        "## Related Entities\n- 관계",
    ]


def test_list_existing_wiki_relations_maps_document_keys() -> None:
    """누적 관계 Row를 Schema와 Persistence가 공유하는 관계 계획으로 변환한다."""
    connection = _FakeConnection(
        [
            {
                "source_document_kind": "entity",
                "source_document_key": "obsidian",
                "target_document_kind": "concept",
                "target_document_key": "연결-노트",
                "relation_type": "applies_concept",
                "metadata": {"confidence": 0.9},
            }
        ]
    )

    result = asyncio.run(
        list_existing_wiki_relations(
            connection,  # type: ignore[arg-type]
            namespace_key="user/user-1",
        )
    )

    assert result[0].source_document_key == "obsidian"
    assert result[0].target_document_key == "연결-노트"
    assert result[0].metadata == {"confidence": 0.9}
    query, _ = connection.executed[0]
    assert "relation.status = 'active'" in query
    assert "relation.review_status <> 'rejected'" in query
    assert connection.executed[0][1] == ("user/user-1",)


def _sample_relation(
    *,
    observed: bool | None = True,
    confidence: object = 0.82,
) -> WikiRelationPlan:
    """관계 근거 수명주기 테스트에 사용할 Wiki 관계 계획을 만든다."""
    metadata: dict[str, object] = {
        "evidence": "서울에 폭염 경보가 발효됐다.",
        "provenance_kind": "source_explicit",
        "confidence": confidence,
        "review_status": "accepted",
        "model": "gpt-4.1-mini",
        "model_version": "2026-07-01",
        "prompt_key": "personal-wiki-relation",
        "prompt_version": 3,
        "disposition": "connect",
    }
    if observed is not None:
        metadata["observed_in_current_build"] = observed
    return WikiRelationPlan(
        source_document_key="서울",
        source_document_kind="entity",
        target_document_key="폭염",
        target_document_kind="concept",
        relation_type="applies_concept",
        metadata=metadata,
    )


def _sample_relation_plan(
    relations: list[WikiRelationPlan], *, extracted_relation_count: int
) -> WikiBuildPlan:
    """관계 관측 선택 로직에 필요한 최소 Wiki Build 계획을 만든다."""
    artifact = GeneratedArtifact(file_path="artifact.md", content="")
    return WikiBuildPlan(
        entities=[],
        concepts=[],
        schema=WikiDocumentPlan(
            document_kind="schema",
            document_key="root",
            file_path="schema/schema.md",
            domain=None,
            title="Schema",
            summary="",
            normalized_content="schema",
            action="update",
        ),
        relations=relations,
        index=artifact,
        source_manifest=artifact,
        log_entry=artifact,
        extracted_relation_count=extracted_relation_count,
    )


def test_relation_persistence_values_separates_trace_and_transient_marker() -> None:
    """관계 Metadata의 근거·추적 값은 컬럼화하고 Build 전용 표식은 제거한다."""
    values = _relation_persistence_values(_sample_relation())

    assert values.provenance_kind == "source_explicit"
    assert values.confidence == pytest.approx(0.82)
    assert values.review_status == "accepted"
    assert values.evidence == "서울에 폭염 경보가 발효됐다."
    assert values.model_name == "gpt-4.1-mini"
    assert values.model_version == "2026-07-01"
    assert values.prompt_key == "personal-wiki-relation"
    assert values.prompt_version == "3"
    assert "observed_in_current_build" not in values.metadata
    assert values.metadata["disposition"] == "connect"


@pytest.mark.parametrize(
    ("metadata_key", "invalid_value"),
    [
        ("provenance_kind", "guessed"),
        ("confidence", 1.01),
        ("confidence", True),
        ("review_status", "approved"),
    ],
)
def test_relation_persistence_values_rejects_invalid_lifecycle_values(
    metadata_key: str, invalid_value: object
) -> None:
    """DB Check와 어긋나는 관계 근거 값은 SQL 실행 전에 거절한다."""
    relation = _sample_relation()
    relation.metadata[metadata_key] = invalid_value

    with pytest.raises(ValueError):
        _relation_persistence_values(relation)


def test_observed_relations_for_build_uses_explicit_marker() -> None:
    """누적 관계 중 이번 Build 표식이 있는 관계만 원본 support로 선택한다."""
    observed = _sample_relation(observed=True)
    historical = _sample_relation(observed=None)
    historical = WikiRelationPlan(
        source_document_key=historical.source_document_key,
        source_document_kind=historical.source_document_kind,
        target_document_key="온열질환",
        target_document_kind=historical.target_document_kind,
        relation_type=historical.relation_type,
        metadata=historical.metadata,
    )
    plan = _sample_relation_plan(
        [historical, observed],
        extracted_relation_count=1,
    )

    assert _observed_relations_for_build(plan) == [observed]


def test_observed_relations_for_build_does_not_guess_ambiguous_legacy_plan() -> None:
    """기존·신규가 섞인 표식 없는 계획을 현재 원본 support로 잘못 귀속하지 않는다."""
    relation = _sample_relation(observed=None)
    plan = _sample_relation_plan([relation], extracted_relation_count=0)

    assert _observed_relations_for_build(plan) == []


class _SequencedFakeConnection:
    """execute 호출 순서대로 서로 다른 고정 Row를 반환하는 Test Double."""

    def __init__(self, rows: list[dict[str, Any] | list[dict[str, Any]] | None]) -> None:
        """순서대로 반환할 Row와 빈 SQL 실행 내역을 초기화한다."""
        self._rows = list(rows)
        self.executed: list[tuple[str, tuple[Any, ...]]] = []

    async def execute(self, query: str, params: tuple[Any, ...]) -> _FakeCursor:
        """실행 SQL과 Parameter를 기록하고 다음 순서의 Row Cursor를 반환한다."""
        self.executed.append((query, params))
        row = self._rows.pop(0) if self._rows else None
        return _FakeCursor(row)


def _sha256(text: str) -> str:
    """테스트에서 기대 content_hash를 계산한다."""
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def test_register_user_url_source_registers_event_and_document() -> None:
    """이벤트·문서 Head를 등록하고 최신 Version 비교 기준을 함께 반환하는지 검증한다."""
    url = "https://finance.naver.com/sise/sise_index.naver?code=KOSPI"
    connection = _SequencedFakeConnection(
        [
            {"id": "event-row-1"},
            {"id": "doc-1"},
            {"version": 2, "content_hash": "b" * 64},
        ]
    )

    result = asyncio.run(
        register_user_url_source(
            connection,  # type: ignore[arg-type]
            user_id="user-1",
            url=url,
            source_event_id="user-url-abc",
        )
    )

    assert result == RegisteredUrlSource(
        source_event_row_id="event-row-1",
        source_document_id="doc-1",
        latest_version=2,
        latest_content_hash="b" * 64,
    )
    event_query, event_params = connection.executed[0]
    assert "agent.wiki_source_events" in event_query
    assert "ON CONFLICT (user_id, source_event_id)" in event_query
    assert event_params[:3] == ("user-1", "user-url-abc", url)
    document_query, document_params = connection.executed[1]
    assert "agent.user_source_documents" in document_query
    assert "ON CONFLICT (namespace_key, canonical_url)" in document_query
    assert document_params[:4] == ("user-1", "user/user-1", url, _sha256(url))


def test_register_user_url_source_without_versions_returns_none_baseline() -> None:
    """저장된 Version이 없으면 비교 기준을 None으로 반환하는지 검증한다."""
    connection = _SequencedFakeConnection(
        [{"id": "event-row-1"}, {"id": "doc-1"}, None]
    )

    result = asyncio.run(
        register_user_url_source(
            connection,  # type: ignore[arg-type]
            user_id="user-1",
            url="https://dart.fss.or.kr/",
            source_event_id="user-url-dart",
        )
    )

    assert result.latest_version is None
    assert result.latest_content_hash is None


def test_save_user_url_document_version_skips_when_hash_unchanged() -> None:
    """content_hash가 최신 Version과 같으면 새 Version을 만들지 않는지 검증한다."""
    raw_content = "# 코스피\n\n지수 요약"
    connection = _SequencedFakeConnection(
        [{"version": 3, "content_hash": _sha256(raw_content)}]
    )

    result = asyncio.run(
        save_user_url_document_version(
            connection,  # type: ignore[arg-type]
            user_id="user-1",
            source_document_id="doc-1",
            source_event_row_id="event-row-1",
            title="KOSPI",
            raw_content=raw_content,
        )
    )

    assert result is None
    assert len(connection.executed) == 1


def test_save_user_url_document_version_creates_first_version() -> None:
    """첫 수집이면 version 1을 만들고 문서 Head hash를 갱신하는지 검증한다."""
    raw_content = "# 코스피\n\n지수 요약"
    connection = _SequencedFakeConnection([None, {"id": "version-row-1"}, None])

    result = asyncio.run(
        save_user_url_document_version(
            connection,  # type: ignore[arg-type]
            user_id="user-1",
            source_document_id="doc-1",
            source_event_row_id="event-row-1",
            title="KOSPI",
            raw_content=raw_content,
            resolved_url="https://finance.naver.com/resolved",
        )
    )

    assert result == SavedUserSourceVersion(
        source_version_id="version-row-1",
        version=1,
        content_hash=_sha256(raw_content),
    )
    insert_query, insert_params = connection.executed[1]
    assert "agent.user_source_document_versions" in insert_query
    assert insert_params[0] == "doc-1"
    assert insert_params[3] == 1
    assert insert_params[4] == "KOSPI"
    update_query, update_params = connection.executed[2]
    assert "UPDATE agent.user_source_documents" in update_query
    assert update_params == (1, _sha256(raw_content), "doc-1")


def test_save_user_url_document_version_increments_version_on_change() -> None:
    """내용이 바뀌면 최신 Version + 1로 새 스냅샷을 저장하는지 검증한다."""
    connection = _SequencedFakeConnection(
        [
            {"version": 2, "content_hash": "c" * 64},
            {"id": "version-row-3"},
            None,
        ]
    )

    result = asyncio.run(
        save_user_url_document_version(
            connection,  # type: ignore[arg-type]
            user_id="user-1",
            source_document_id="doc-1",
            source_event_row_id=None,
            title="갱신된 제목",
            raw_content="새 본문",
        )
    )

    assert result is not None
    assert result.version == 3


def test_mark_url_source_event_rejects_unknown_status() -> None:
    """허용되지 않은 이벤트 상태는 ValueError를 발생시키는지 검증한다."""
    connection = _SequencedFakeConnection([])

    with pytest.raises(ValueError):
        asyncio.run(
            mark_url_source_event(
                connection,  # type: ignore[arg-type]
                source_event_row_id="event-row-1",
                status="queued",
            )
        )
    assert connection.executed == []


def test_mark_url_source_event_records_failure_details() -> None:
    """실패 상태가 오류 코드·메시지와 함께 이벤트 Row에 기록되는지 검증한다."""
    connection = _SequencedFakeConnection([None])

    asyncio.run(
        mark_url_source_event(
            connection,  # type: ignore[arg-type]
            source_event_row_id="event-row-1",
            status="failed",
            error_code="http_451",
            error_message="차단된 URL",
        )
    )

    query, params = connection.executed[0]
    assert "UPDATE agent.wiki_source_events" in query
    assert params == (
        "failed",
        "http_451",
        "차단된 URL",
        "failed",
        "failed",
        "event-row-1",
    )


class _SequencedConnection:
    """호출 순서별 응답 목록을 돌려주는 Connection Test Double."""

    def __init__(self, responses: list[dict[str, Any] | list[dict[str, Any]] | None]) -> None:
        """순서별 응답과 빈 SQL 실행 내역을 초기화한다."""
        self._responses = responses
        self.executed: list[tuple[str, tuple[Any, ...]]] = []

    async def execute(self, query: str, params: tuple[Any, ...]) -> _FakeCursor:
        """실행된 SQL을 기록하고 순서에 맞는 고정 Cursor를 반환한다."""
        self.executed.append((query, params))
        row = self._responses.pop(0) if self._responses else None
        return _FakeCursor(row)


def _sample_source() -> UserSourceDocumentForAgent:
    """Wiki Build 대상 사용자 원본 Version 예시."""
    return UserSourceDocumentForAgent(
        source_document_id="doc-1",
        source_document_version_id="version-1",
        source_event_id="event-1",
        user_id="user-1",
        namespace_key="user/user-1",
        source_type="url",
        canonical_url="https://example.com",
        version=1,
        title="원본",
        author=None,
        published_at=None,
        clipped_on=None,
        description=None,
    )


def _sample_plan_document() -> WikiDocumentPlan:
    """저장 예정인 entity 문서 계획 예시."""
    return WikiDocumentPlan(
        document_kind="entity",
        document_key="postgresql",
        file_path="entities/postgresql.md",
        domain=None,
        title="PostgreSQL",
        summary="요약",
        normalized_content="## Description\n동일한 본문",
        action="create",
    )


def test_upsert_wiki_document_reuses_existing_document_with_same_content() -> None:
    """새 Head의 내용이 기존 문서와 동일하면 INSERT 없이 재사용한다(PWIKI-008)."""
    duplicate = {
        "id": "doc-existing",
        "document_kind": "entity",
        "document_key": "postgres",
        "file_path": "entities/postgres.md",
        "current_version": 2,
    }
    connection = _SequencedConnection(
        [None, duplicate, {"id": "version-existing"}, None]
    )

    persisted, changed = asyncio.run(
        _upsert_wiki_document(
            connection,  # type: ignore[arg-type]
            source=_sample_source(),
            document=_sample_plan_document(),
            job_id="job-1",
        )
    )

    assert changed is False
    assert persisted.action == "deduplicated"
    assert persisted.document_id == "doc-existing"
    assert persisted.document_key == "postgres"
    assert persisted.version == 2
    assert not any(
        "INSERT INTO agent.wiki_documents" in query
        for query, _ in connection.executed
    )


def test_upsert_wiki_document_skips_version_when_update_duplicates_other_document() -> None:
    """갱신 내용이 다른 문서와 동일하면 새 Version을 만들지 않는다(PWIKI-008)."""
    head = {"id": "doc-head", "current_version": 3, "content_hash": "b" * 64}
    duplicate = {
        "id": "doc-existing",
        "document_kind": "entity",
        "document_key": "postgres",
        "file_path": "entities/postgres.md",
        "current_version": 2,
    }
    connection = _SequencedConnection(
        [head, duplicate, {"id": "version-head-3"}, None]
    )

    persisted, changed = asyncio.run(
        _upsert_wiki_document(
            connection,  # type: ignore[arg-type]
            source=_sample_source(),
            document=_sample_plan_document(),
            job_id="job-1",
        )
    )

    assert changed is False
    assert persisted.action == "deduplicated"
    assert persisted.document_id == "doc-head"
    assert persisted.version == 3
    assert not any(
        "INSERT INTO agent.wiki_document_versions" in query
        for query, _ in connection.executed
    )
    assert not any(
        "UPDATE agent.wiki_documents" in query for query, _ in connection.executed
    )


def test_list_related_wiki_keywords_maps_rows() -> None:
    """이웃 Row를 연결 강도·관계 유형이 담긴 RelatedWikiKeyword로 변환한다."""
    connection = _FakeConnection(
        [
            {
                "title": "서킷 브레이커",
                "document_kind": "concept",
                "weight": 2.0,
                "relation_types": ["applies_concept"],
            },
            {
                "title": "  투자자 예탁금  ",
                "document_kind": "concept",
                "weight": 1.0,
                "relation_types": ["applies_concept", "related_concept"],
            },
            {"title": "   ", "document_kind": "entity", "weight": 1.0, "relation_types": []},
        ]
    )

    related = asyncio.run(
        list_related_wiki_keywords(
            connection,  # type: ignore[arg-type]
            user_id="user-1",
            topic="코스피",
            limit=3,
        )
    )

    # 제목이 빈 Row는 검색어로 쓸 수 없어 버린다.
    assert [item.title for item in related] == ["서킷 브레이커", "투자자 예탁금"]
    assert related[0].weight == 2.0
    assert related[1].relation_types == ("applies_concept", "related_concept")


def test_list_wiki_graph_relation_snapshot_maps_heads_titles_and_support() -> None:
    """Graph Gate Snapshot에 Head 정책·endpoint 표시값·active support를 보존한다."""
    connection = _FakeConnection(
        [
            {
                "source_document_kind": "concept",
                "source_document_key": "weather",
                "source_title": " 날씨 ",
                "source_domain": "field",
                "target_document_kind": "concept",
                "target_document_key": "heatwave",
                "target_title": "폭염",
                "target_domain": "phenomenon",
                "relation_type": "subtopic_of",
                "status": "active",
                "review_status": "accepted",
                "provenance_kind": "semantic_inference",
                "confidence": 0.84,
                "weight": 1.0,
                "supported": True,
            }
        ]
    )

    snapshot = asyncio.run(
        list_wiki_graph_relation_snapshot(
            connection,  # type: ignore[arg-type]
            namespace_key="user/user-1",
        )
    )

    assert len(snapshot) == 1
    relation = snapshot[0]
    assert relation.source_title == "날씨"
    assert relation.target_title == "폭염"
    assert relation.relation_type == "subtopic_of"
    assert relation.review_status == "accepted"
    assert relation.provenance_kind == "semantic_inference"
    assert relation.confidence == pytest.approx(0.84)
    assert relation.supported is True

    query, params = connection.executed[0]
    assert "source_version.title AS source_title" in query
    assert "target_version.title AS target_title" in query
    assert "FROM agent.wiki_relation_supports AS support" in query
    assert "support.status = 'active'" in query
    assert "source_version.version = source.current_version" in query
    assert "target_version.version = target.current_version" in query
    assert "relation.status = 'active'" not in query
    assert "relation.review_status = 'accepted'" not in query
    assert params == ("user/user-1",)


def test_list_related_wiki_keywords_scopes_and_limits_query() -> None:
    """Namespace·1홉·상한 조건을 SQL과 Parameter에 담아 조회한다."""
    connection = _FakeConnection([])

    asyncio.run(
        list_related_wiki_keywords(
            connection,  # type: ignore[arg-type]
            user_id="user-1",
            topic="  코스피  ",
            limit=5,
        )
    )

    query, params = connection.executed[0]
    assert "FROM agent.wiki_document_relations AS relation" in query
    assert "relation.status = 'active'" in query
    assert "relation.review_status <> 'rejected'" in query
    assert "WHEN 'subtopic_of' THEN 1.0" in query
    assert "WHEN 'associated_with' THEN 0.5" in query
    assert "MAX(" in query
    assert "HAVING MAX(" in query
    assert "peer.document_kind IN ('entity', 'concept')" in query
    # 기관·언론사 이름을 검색어로 쓰면 주제가 아니라 그 회사 소식이 걸린다.
    assert "COALESCE(peer.domain, '') <> 'organization'" in query
    assert "peer.id NOT IN (SELECT id FROM origin)" in query
    assert "ORDER BY weight DESC, title ASC" in query
    # 토픽은 앞뒤 공백을 제거해 노드 제목·document_key 양쪽과 대조한다.
    assert params == ("user/user-1", "코스피", "코스피", "user/user-1", 5)


def test_list_related_wiki_keywords_supports_pre_lifecycle_schema_fallback() -> None:
    """Migration 전 운영 폴백 SQL은 새 relation lifecycle 컬럼을 참조하지 않는다."""
    connection = _FakeConnection([])

    asyncio.run(
        list_related_wiki_keywords(
            connection,  # type: ignore[arg-type]
            user_id="user-1",
            topic="코스피",
            limit=2,
            lifecycle_aware=False,
        )
    )

    query, params = connection.executed[0]
    assert "relation.status = 'active'" not in query
    assert "relation.review_status" not in query
    assert "FROM agent.wiki_relation_supports" not in query
    assert params == ("user/user-1", "코스피", "코스피", "user/user-1", 2)


def test_list_related_wiki_keywords_skips_query_when_disabled() -> None:
    """상한이 0 이하거나 토픽이 비면 DB를 조회하지 않는다."""
    connection = _FakeConnection([])

    assert (
        asyncio.run(
            list_related_wiki_keywords(
                connection,  # type: ignore[arg-type]
                user_id="user-1",
                topic="코스피",
                limit=0,
            )
        )
        == []
    )
    assert (
        asyncio.run(
            list_related_wiki_keywords(
                connection,  # type: ignore[arg-type]
                user_id="user-1",
                topic="   ",
                limit=5,
            )
        )
        == []
    )
    assert connection.executed == []


def test_sync_wiki_relation_supports_replaces_source_support_and_supersedes_head() -> None:
    """Build마다 원본 support를 교체하고 지지가 사라진 관계 Head를 supersede한다."""
    relation = _sample_relation()
    connection = _SequencedConnection(
        [
            [{"relation_id": "relation-old"}],
            [
                {
                    "id": "document-seoul",
                    "document_kind": "entity",
                    "document_key": "서울",
                },
                {
                    "id": "document-heatwave",
                    "document_kind": "concept",
                    "document_key": "폭염",
                },
            ],
            {"id": "relation-new"},
            None,
            None,
            [{"id": "relation-old"}],
        ]
    )

    result = asyncio.run(
        sync_wiki_relation_supports(
            connection,  # type: ignore[arg-type]
            namespace_key="user/user-1",
            source_document_id="source-document-1",
            source_document_version_id="source-version-1",
            job_id="job-1",
            relations=[relation],
            observed_relations=[relation],
        )
    )

    assert result.observed_relation_count == 1
    assert result.stored_support_count == 1
    assert result.superseded_support_count == 1
    assert result.superseded_relation_count == 1

    stale_query, stale_params = connection.executed[0]
    assert "UPDATE agent.wiki_relation_supports" in stale_query
    assert "status = 'superseded'" in stale_query
    assert "source_version.source_document_id = %s" in stale_query
    assert "%s IS NOT NULL" not in stale_query
    assert stale_params == (
        "user/user-1",
        "source-version-1",
        "source-document-1",
    )

    head_query, head_params = connection.executed[2]
    assert "INSERT INTO agent.wiki_document_relations" in head_query
    assert "superseded_at = NULL" in head_query
    assert head_params[:4] == (
        "document-seoul",
        "document-heatwave",
        "user/user-1",
        "applies_concept",
    )
    assert head_params[5:12] == (
        "source_explicit",
        0.82,
        "accepted",
        "gpt-4.1-mini",
        "2026-07-01",
        "personal-wiki-relation",
        "3",
    )

    support_query, support_params = connection.executed[3]
    assert "INSERT INTO agent.wiki_relation_supports" in support_query
    assert "ON CONFLICT (relation_id, source_document_version_id, build_job_id)" in support_query
    assert support_params[:8] == (
        "relation-new",
        "user/user-1",
        "source-version-1",
        "job-1",
        "source_explicit",
        0.82,
        "accepted",
        "서울에 폭염 경보가 발효됐다.",
    )
    assert "observed_in_current_build" not in support_params[12].obj

    supersede_head_query, _ = connection.executed[5]
    assert "NOT EXISTS" in supersede_head_query
    assert "support.status = 'active'" in supersede_head_query


def test_sync_wiki_relation_supports_keeps_head_when_another_support_remains() -> None:
    """현재 원본의 support가 빠져도 다른 active support가 있으면 Head를 유지한다."""
    connection = _SequencedConnection(
        [
            [{"relation_id": "relation-shared"}],
            [],
            None,
            [],
        ]
    )

    result = asyncio.run(
        sync_wiki_relation_supports(
            connection,  # type: ignore[arg-type]
            namespace_key="user/user-1",
            source_document_id="source-document-1",
            source_document_version_id="source-version-1",
            job_id="job-2",
            relations=[],
            observed_relations=[],
        )
    )

    assert result.stored_support_count == 0
    assert result.superseded_support_count == 1
    assert result.superseded_relation_count == 0
    representative_query, _ = connection.executed[2]
    assert "WITH representative AS" in representative_query
    supersede_query, params = connection.executed[3]
    assert "NOT EXISTS" in supersede_query
    assert params[0] == "user/user-1"
