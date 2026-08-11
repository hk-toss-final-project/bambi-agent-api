"""사용자 클리핑·URL 원본과 Job의 원자적 저장 SQL을 검증한다."""

import asyncio
from datetime import UTC, date, datetime
from typing import Any

import pytest

from infrastructure.persistence.features import source_ingestion
from infrastructure.persistence.features.jobs import EnqueuedWikiBuildJob
from infrastructure.persistence.features.personal_wiki import SavedUserSourceVersion
from infrastructure.persistence.features.personal_wiki import UserSourceDocumentForAgent
from infrastructure.persistence.features.source_ingestion import (
    ContentMarkBindingNotFoundError,
    PersistedMcpSourceSubmission,
    PersistedSourceSubmission,
    _upsert_onboarding_seed_version,
    deactivate_content_mark_and_enqueue_rebuild,
    enqueue_wiki_rebuild_for_source,
    save_fetched_url_and_enqueue,
    save_mcp_source_submission,
    save_web_clipping_and_enqueue,
)


class _FakeCursor:
    """한 SQL 호출에 지정된 Row를 반환하는 Cursor Test Double."""

    def __init__(self, row: dict[str, Any] | None) -> None:
        self._row = row

    async def fetchone(self) -> dict[str, Any] | None:
        """지정된 단일 Row를 반환한다."""
        return self._row

    async def fetchall(self) -> list[dict[str, Any]]:
        """SCH-009 조용 시간 조정처럼 fetchall을 쓰는 호출을 위한 목록을 반환한다."""
        return [self._row] if self._row is not None else []


class _SequencedConnection:
    """SQL 호출 순서별 Row와 실행 내역을 보존하는 Connection Test Double."""

    def __init__(self, rows: list[dict[str, Any] | None]) -> None:
        self._rows = list(rows)
        self.executed: list[tuple[str, tuple[Any, ...]]] = []

    async def execute(self, query: str, params: tuple[Any, ...]) -> _FakeCursor:
        """SQL과 Parameter를 기록하고 다음 Row를 반환한다."""
        self.executed.append((query, params))
        return _FakeCursor(self._rows.pop(0) if self._rows else None)


def test_onboarding_selection_change_appends_version_to_single_active_head() -> None:
    """선택 변경은 새 Source Head가 아니라 기존 활성 Head의 다음 Version이 된다."""
    connection = _SequencedConnection(
        [
            None,  # advisory lock
            {"id": "onboarding-head-1"},
            {"id": "seed-v1", "version": 1, "content_hash": "a" * 64},
            {"id": "seed-v2"},
            None,  # Head current_version 갱신
        ]
    )

    result = asyncio.run(
        _upsert_onboarding_seed_version(
            connection,  # type: ignore[arg-type]
            user_id="user-1",
            namespace_key="user/user-1",
            source_event_row_id="event-v2",
            title="온보딩 관심 주제 시드",
            content="# 변경된 선택",
            content_hash="b" * 64,
            metadata={"context_contract_version": 1},
        )
    )

    assert result == ("onboarding-head-1", "seed-v2", 2)
    sql = "\n".join(query for query, _params in connection.executed)
    assert "source_type = 'onboarding_seed'" in sql
    assert "status = 'active'" in sql
    assert "INSERT INTO agent.user_source_document_versions" in sql
    assert "INSERT INTO agent.user_source_documents" not in sql
    update_query, update_params = connection.executed[-1]
    assert "current_version = %s" in update_query
    assert update_params[0:2] == (2, "b" * 64)


def test_same_onboarding_selection_reuses_current_version() -> None:
    """같은 시드 본문 재전송은 Version Row를 추가하지 않는다."""
    connection = _SequencedConnection(
        [
            None,
            {"id": "onboarding-head-1"},
            {"id": "seed-v2", "version": 2, "content_hash": "b" * 64},
        ]
    )

    result = asyncio.run(
        _upsert_onboarding_seed_version(
            connection,  # type: ignore[arg-type]
            user_id="user-1",
            namespace_key="user/user-1",
            source_event_row_id="event-v2",
            title="온보딩 관심 주제 시드",
            content="# 같은 선택",
            content_hash="b" * 64,
            metadata={"context_contract_version": 1},
        )
    )

    assert result == ("onboarding-head-1", "seed-v2", 2)
    assert not any(
        "INSERT INTO agent.user_source_document_versions" in query
        for query, _params in connection.executed
    )


def test_save_web_clipping_persists_frontmatter_and_wiki_job() -> None:
    """클리핑 Frontmatter·Markdown과 Wiki Job이 같은 실행 경계에 포함되는지 검증한다."""
    connection = _SequencedConnection(
        [
            {"id": "event-1"},
            None,
            {"id": "source-1"},
            None,
            {"id": "source-version-1"},
            None,
            None,
            {"id": "job-1"},
            None,
        ]
    )

    result = asyncio.run(
        save_web_clipping_and_enqueue(
            connection,  # type: ignore[arg-type]
            user_id="user-1",
            source_event_id="clip-1",
            source_url="https://example.com/article",
            title="제목",
            content="# Markdown 본문",
            author="작성자",
            published_at=datetime(2026, 7, 1, tzinfo=UTC),
            clipped_on=date(2026, 7, 16),
            description="설명",
            tags=["ai", "wiki"],
            occurred_at=None,
            memo="중요",
            request_id="request-1",
        )
    )

    assert result == PersistedSourceSubmission(
        source_document_id="source-1",
        source_document_version_id="source-version-1",
        source_version=1,
        source_event_row_id="event-1",
        job_id="job-1",
        job_created=True,
    )
    version_sql, version_params = connection.executed[4]
    assert "agent.user_source_document_versions" in version_sql
    assert version_params[4:11] == (
        "제목",
        "작성자",
        datetime(2026, 7, 1, tzinfo=UTC),
        date(2026, 7, 16),
        "설명",
        ["ai", "wiki"],
        "# Markdown 본문",
    )
    binding_sql, binding_params = connection.executed[6]
    assert "agent.user_source_bindings" in binding_sql
    assert binding_params[-1] == "event-1"
    job_sql, job_params = connection.executed[7]
    assert "'personal_wiki_build'" in job_sql
    assert job_params is not None
    assert job_params[0] == "SVC-002"
    assert job_params[2] == "clip-1:v1"
    assert job_params[4] == "request-1"


def test_save_web_clipping_reuses_same_source_version_and_job() -> None:
    """같은 본문 재요청이 원본 Version과 Wiki Job을 중복 생성하지 않는지 검증한다."""
    from agent.wiki_builder.features.vault import compute_content_hash

    content = "# 동일 본문"
    connection = _SequencedConnection(
        [
            {"id": "event-1"},
            {"id": "source-1"},
            {
                "id": "source-version-1",
                "version": 1,
                "content_hash": compute_content_hash(content),
            },
            None,
            {"id": "job-1"},
            None,
        ]
    )

    result = asyncio.run(
        save_web_clipping_and_enqueue(
            connection,  # type: ignore[arg-type]
            user_id="user-1",
            source_event_id="clip-1",
            source_url="https://example.com/article",
            title="제목",
            content=content,
            author=None,
            published_at=None,
            clipped_on=None,
            description=None,
            tags=[],
            occurred_at=None,
            memo=None,
            request_id="request-2",
        )
    )

    assert result.source_document_version_id == "source-version-1"
    assert result.job_id == "job-1"
    assert not any(
        "INSERT INTO agent.user_source_document_versions" in sql
        for sql, _ in connection.executed
    )


def test_save_mcp_source_submission_persists_without_enqueueing_job() -> None:
    """MCP Source 저장이 Build Job 없이 원본 Version만 멱등 저장하는지 검증한다."""
    connection = _SequencedConnection(
        [
            {"id": "event-1"},
            None,
            {"id": "source-1"},
            None,
            {"id": "source-version-1"},
            None,
        ]
    )

    result = asyncio.run(
        save_mcp_source_submission(
            connection,  # type: ignore[arg-type]
            user_id="user-1",
            title="Claude가 보낸 제목",
            content="# MCP로 받은 본문",
            tags=["ai"],
            memo="메모",
            occurred_at=None,
        )
    )

    assert result == PersistedMcpSourceSubmission(
        source_document_id="source-1",
        source_document_version_id="source-version-1",
        source_version=1,
        source_event_row_id="event-1",
    )
    assert len(connection.executed) == 7
    event_sql, _event_params = connection.executed[0]
    assert "'mcp_submission'" in event_sql
    version_sql, _version_params = connection.executed[4]
    assert "agent.user_source_document_versions" in version_sql


def test_save_mcp_source_submission_reuses_same_version_for_identical_content() -> None:
    """동일 본문 재제출이 새 Version이나 Event Row를 추가하지 않는지 검증한다."""
    from agent.wiki_builder.features.vault import compute_content_hash

    content = "# 동일 MCP 본문"
    connection = _SequencedConnection(
        [
            {"id": "event-1"},
            {"id": "source-1"},
            {
                "id": "source-version-1",
                "version": 1,
                "content_hash": compute_content_hash(content),
            },
        ]
    )

    result = asyncio.run(
        save_mcp_source_submission(
            connection,  # type: ignore[arg-type]
            user_id="user-1",
            title="제목",
            content=content,
            tags=[],
            memo=None,
            occurred_at=None,
        )
    )

    assert result.source_document_version_id == "source-version-1"
    assert len(connection.executed) == 4
    assert not any(
        "INSERT INTO agent.user_source_document_versions" in sql
        for sql, _ in connection.executed
    )


def test_enqueue_wiki_rebuild_for_source_reuses_source_event_id(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """재빌드 트리거가 조회된 원본의 event_id·version으로 멱등 Job을 등록하는지 검증한다."""
    fetched_kwargs: dict[str, Any] = {}
    enqueued_kwargs: dict[str, Any] = {}

    async def fake_get_source(connection: Any, **kwargs: Any) -> UserSourceDocumentForAgent:
        """조회 인자를 기록하고 고정된 원본 Version을 반환한다."""
        fetched_kwargs.update(kwargs)
        return UserSourceDocumentForAgent(
            source_document_id="source-1",
            source_document_version_id="source-version-1",
            source_event_id="mcp-write:abc123",
            user_id="user-1",
            namespace_key="user/user-1",
            source_type="mcp_submission",
            canonical_url=None,
            version=2,
            title="제목",
            author=None,
            published_at=None,
            clipped_on=None,
            description=None,
        )

    async def fake_enqueue(connection: Any, **kwargs: Any) -> EnqueuedWikiBuildJob:
        """후속 Wiki Job 등록 인자를 기록한다."""
        enqueued_kwargs.update(kwargs)
        return EnqueuedWikiBuildJob(job_id="wiki-job-2", created=True)

    monkeypatch.setattr(
        source_ingestion, "get_user_source_document_version_for_agent", fake_get_source
    )
    monkeypatch.setattr(source_ingestion, "enqueue_personal_wiki_build_job", fake_enqueue)

    result = asyncio.run(
        enqueue_wiki_rebuild_for_source(
            object(),  # type: ignore[arg-type]
            user_id="user-1",
            source_document_version_id="source-version-1",
            request_id="request-3",
        )
    )

    assert result == EnqueuedWikiBuildJob(job_id="wiki-job-2", created=True)
    assert fetched_kwargs["user_id"] == "user-1"
    assert fetched_kwargs["source_document_version_id"] == "source-version-1"
    assert enqueued_kwargs["source_event_id"] == "mcp-write:abc123"
    assert enqueued_kwargs["source_version"] == 2
    assert enqueued_kwargs["feature_id"] == "MCPTOOL-014"


def test_enqueue_wiki_rebuild_for_source_rejects_unknown_version(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """존재하지 않는 원본 Version은 Job 등록 없이 거부한다."""

    async def fake_missing(connection: Any, **kwargs: Any) -> None:
        """원본을 찾지 못한 상황을 반환한다."""
        return None

    async def fail_enqueue(connection: Any, **kwargs: Any) -> EnqueuedWikiBuildJob:
        """원본이 없을 때 Job이 등록되면 테스트를 실패시킨다."""
        raise AssertionError("존재하지 않는 원본에 재빌드 Job을 등록했습니다.")

    monkeypatch.setattr(
        source_ingestion, "get_user_source_document_version_for_agent", fake_missing
    )
    monkeypatch.setattr(source_ingestion, "enqueue_personal_wiki_build_job", fail_enqueue)

    with pytest.raises(ValueError):
        asyncio.run(
            enqueue_wiki_rebuild_for_source(
                object(),  # type: ignore[arg-type]
                user_id="user-1",
                source_document_version_id="missing-version",
                request_id=None,
            )
        )


def test_save_fetched_url_persists_version_and_enqueues_wiki_job(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Jina Markdown 저장 결과가 후속 Wiki Build Job과 연결되는지 검증한다."""
    saved_kwargs: dict[str, Any] = {}
    enqueued_kwargs: dict[str, Any] = {}

    async def fake_save(connection: Any, **kwargs: Any) -> SavedUserSourceVersion:
        """원본 Version 저장 인자를 기록한다."""
        saved_kwargs.update(kwargs)
        return SavedUserSourceVersion(
            source_version_id="source-version-1",
            version=1,
            content_hash="a" * 64,
        )

    async def fake_enqueue(connection: Any, **kwargs: Any) -> EnqueuedWikiBuildJob:
        """후속 Wiki Job 등록 인자를 기록한다."""
        enqueued_kwargs.update(kwargs)
        return EnqueuedWikiBuildJob(job_id="wiki-job-1", created=True)

    monkeypatch.setattr(source_ingestion, "save_user_url_document_version", fake_save)
    monkeypatch.setattr(source_ingestion, "enqueue_personal_wiki_build_job", fake_enqueue)

    result = asyncio.run(
        save_fetched_url_and_enqueue(
            object(),  # type: ignore[arg-type]
            user_id="user-1",
            source_document_id="source-1",
            source_event_id="event-1",
            source_event_row_id="event-row-1",
            title="수집 제목",
            markdown="# Jina 본문",
            resolved_url="https://example.com/final",
            published_at=datetime(2026, 8, 4, tzinfo=UTC),
            image_url="https://cdn.example/cover.jpg",
        )
    )

    assert result == {
        "source_document_id": "source-1",
        "source_document_version_id": "source-version-1",
        "source_version": 1,
        "wiki_build_job_id": "wiki-job-1",
        "unchanged": False,
    }
    assert saved_kwargs["raw_content"] == "# Jina 본문"
    assert saved_kwargs["image_url"] == "https://cdn.example/cover.jpg"
    assert enqueued_kwargs["source_event_id"] == "event-1"
    assert enqueued_kwargs["feature_id"] == "SVC-003"


def test_save_fetched_url_marks_unchanged_event_completed(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """동일 본문 재수집은 Version·Wiki Job 없이 URL 이벤트만 완료하는지 검증한다."""
    marked: dict[str, Any] = {}

    async def fake_save(connection: Any, **kwargs: Any) -> None:
        """동일한 최신 Version이 존재하는 상황을 반환한다."""
        return None

    async def fake_mark(connection: Any, **kwargs: Any) -> None:
        """이벤트 완료 처리 인자를 기록한다."""
        marked.update(kwargs)

    async def fail_enqueue(connection: Any, **kwargs: Any) -> EnqueuedWikiBuildJob:
        """변경 없는 본문에 Wiki Job이 생기면 테스트를 실패시킨다."""
        raise AssertionError("변경 없는 본문에 Wiki Job을 등록했습니다.")

    monkeypatch.setattr(source_ingestion, "save_user_url_document_version", fake_save)
    monkeypatch.setattr(source_ingestion, "mark_url_source_event", fake_mark)
    monkeypatch.setattr(source_ingestion, "enqueue_personal_wiki_build_job", fail_enqueue)

    result = asyncio.run(
        save_fetched_url_and_enqueue(
            object(),  # type: ignore[arg-type]
            user_id="user-1",
            source_document_id="source-1",
            source_event_id="event-1",
            source_event_row_id="event-row-1",
            title="수집 제목",
            markdown="# 동일 본문",
            resolved_url="https://example.com/final",
            published_at=None,
        )
    )

    assert result == {"source_document_id": "source-1", "unchanged": True}
    assert marked == {"source_event_row_id": "event-row-1", "status": "completed"}


def test_save_content_mark_bookmarks_report_regardless_of_author() -> None:
    """북마크가 작성자와 무관하게 리포트 본문을 북마커 namespace 원본으로 복사·등록하는지 검증한다."""
    from infrastructure.persistence.features.source_ingestion import (
        save_content_mark_and_enqueue,
    )

    connection = _SequencedConnection(
        [
            {
                # 다른 사용자가 작성한 리포트를 user-1이 북마크하는 상황
                "author_user_id": "author-2",
                "content_id": "content-1",
                "version": 2,
                "content_type": "interest_news_card",
                "title": "생성 리포트 제목",
                "summary": "생성 요약",
                "body": "# 생성 본문",
            },
            {"id": "event-1"},
            None,
            {"id": "source-1"},
            None,
            {"id": "source-version-1"},
            None,
            None,
            {"id": "job-1"},
            None,
        ]
    )

    result = asyncio.run(
        save_content_mark_and_enqueue(
            connection,  # type: ignore[arg-type]
            user_id="user-1",
            source_event_id="mark-1",
            content_id="content-1",
            occurred_at=None,
            memo="저장",
            request_id="request-1",
        )
    )

    assert result.source_document_id == "source-1"
    assert result.source_document_version_id == "source-version-1"
    assert result.job_id == "job-1"
    # 후보 조회는 작성자(user_id) 필터 없이 content_id로만 전역 조회한다.
    candidate_sql, candidate_params = connection.executed[0]
    assert "agent.generated_content_candidates" in candidate_sql
    assert "WHERE id::text = %s OR content_id = %s" in candidate_sql
    assert candidate_params == ("content-1", "content-1", "content-1")
    # 물질화 원본·이벤트는 북마크한 사용자(user-1) namespace에 귀속된다.
    event_sql, event_params = connection.executed[1]
    assert "'content_mark'" in event_sql
    assert event_params[0] == "user-1"
    assert event_params[3] == "content-1"
    head_sql, head_params = connection.executed[3]
    assert "agent.user_source_documents" in head_sql
    assert "content_mark" in head_params
    assert "user/user-1" in head_params
    version_sql, version_params = connection.executed[5]
    assert "agent.user_source_document_versions" in version_sql
    assert version_params[4] == "생성 리포트 제목"
    assert version_params[10] == "# 생성 본문"
    # 출처 보존: 원 작성자와 북마커를 메타데이터로 남긴다.
    version_metadata = version_params[12].obj
    assert version_metadata["author_user_id"] == "author-2"
    assert version_metadata["bookmarked_by"] == "user-1"
    binding_sql, binding_params = connection.executed[7]
    assert "agent.user_source_bindings" in binding_sql
    assert binding_params[-1] == "event-1"
    job_sql, job_params = connection.executed[8]
    assert "'personal_wiki_build'" in job_sql
    assert job_params[0] == "SVC-004"


def test_save_content_mark_rejects_unknown_candidate() -> None:
    """대상 생성 콘텐츠가 없으면 저장 없이 도메인 오류를 던지는지 검증한다."""
    import pytest

    from infrastructure.persistence.features.source_ingestion import (
        GeneratedContentNotFoundError,
        save_content_mark_and_enqueue,
    )

    connection = _SequencedConnection([None])

    with pytest.raises(GeneratedContentNotFoundError):
        asyncio.run(
            save_content_mark_and_enqueue(
                connection,  # type: ignore[arg-type]
                user_id="user-1",
                source_event_id="mark-unknown",
                content_id="missing",
                occurred_at=None,
                memo=None,
                request_id="request-1",
            )
        )

    assert len(connection.executed) == 1


def test_deactivate_content_mark_removes_last_binding_and_enqueues_full_rebuild(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """마지막 북마크 연결 해제는 원본 Head를 내리고 전체 재빌드를 등록한다."""
    connection = _SequencedConnection(
        [
            None,
            {
                "id": "binding-1",
                "source_document_id": "source-1",
                "source_document_version_id": "version-1",
            },
            {"id": "delete-event-1"},
            None,
            {"active_count": 0},
            None,
        ]
    )
    enqueued: dict[str, Any] = {}

    async def fake_enqueue(connection: Any, **kwargs: Any) -> EnqueuedWikiBuildJob:
        """전체 재빌드 등록 인자를 기록한다."""
        enqueued.update(kwargs)
        return EnqueuedWikiBuildJob(job_id="rebuild-job-1", created=True)

    monkeypatch.setattr(
        source_ingestion, "enqueue_personal_wiki_rebuild_job", fake_enqueue
    )
    result = asyncio.run(
        deactivate_content_mark_and_enqueue_rebuild(
            connection,  # type: ignore[arg-type]
            user_id="user-1",
            source_event_id="unmark-1",
            marked_source_event_id="mark-1",
            content_id="content-1",
            occurred_at=None,
            memo=None,
            request_id="request-1",
        )
    )

    assert result.job_id == "rebuild-job-1"
    assert result.source_document_id == "source-1"
    sql = "\n".join(query for query, _params in connection.executed)
    assert "UPDATE agent.user_source_bindings" in sql
    assert "UPDATE agent.user_source_documents" in sql
    assert enqueued["removed_source_document_id"] == "source-1"
    assert enqueued["source_event_row_id"] == "delete-event-1"
    assert enqueued["maintenance_pipeline_version"] == "legacy_v1"


def test_deactivate_content_mark_rejects_missing_active_binding() -> None:
    """이미 없거나 다른 콘텐츠의 북마크 연결은 해제하지 않는다."""
    connection = _SequencedConnection([None, None])

    with pytest.raises(ContentMarkBindingNotFoundError):
        asyncio.run(
            deactivate_content_mark_and_enqueue_rebuild(
                connection,  # type: ignore[arg-type]
                user_id="user-1",
                source_event_id="unmark-1",
                marked_source_event_id="mark-missing",
                content_id="content-1",
                occurred_at=None,
                memo=None,
                request_id="request-1",
            )
        )

    assert len(connection.executed) == 2
