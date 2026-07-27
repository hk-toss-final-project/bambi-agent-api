"""개인 Wiki 문서 목록·상세·Build 조회 API를 검증한다."""

from collections.abc import Mapping
from datetime import UTC, datetime

from fastapi.testclient import TestClient

from app.config import Settings
from app.dependencies import AppContainer
from app.main import create_app
from app.services.wiki_documents import WikiDocumentService


class _FakeWikiDocumentRepository:
    """결정적인 Wiki 문서와 Build Snapshot을 반환하는 저장소 대역."""

    async def list_documents(
        self,
        user_id: str,
        *,
        document_kind: str | None,
        limit: int,
        offset: int,
    ) -> Mapping[str, object]:
        """필터와 Pagination 호출을 반영한 문서 목록을 반환한다."""
        return {
            "user_id": user_id,
            "namespace_key": f"user/{user_id}",
            "total": 1,
            "items": [self._summary()],
        }

    async def get_document(
        self, user_id: str, document_id: str
    ) -> Mapping[str, object] | None:
        """알려진 ID의 Markdown·출처·관계 상세를 반환한다."""
        if document_id != "document-1":
            return None
        return {
            **self._summary(),
            "feature_id": "PWIKI-003",
            "user_id": user_id,
            "namespace_key": f"user/{user_id}",
            "markdown": "---\ntype: entity\n---\n# Obsidian",
            "source_metadata": {"aliases": ["옵시디언"]},
            "sources": [
                {
                    "source_document_id": "source-1",
                    "source_document_version_id": "source-version-1",
                    "source_type": "web_clipping",
                    "source_version": 1,
                    "title": "원본",
                    "canonical_url": "https://example.com",
                    "relation_type": "source",
                }
            ],
            "relations": [],
        }

    async def get_wiki_version(
        self, user_id: str, wiki_version_id: str
    ) -> Mapping[str, object] | None:
        """알려진 ID의 Wiki Build 문서 구성을 반환한다."""
        if wiki_version_id != "wiki-version-1":
            return None
        now = datetime(2026, 7, 16, tzinfo=UTC)
        return {
            "wiki_version_id": wiki_version_id,
            "user_id": user_id,
            "namespace_key": f"user/{user_id}",
            "version": 1,
            "status": "active",
            "document_count": 1,
            "chunk_count": 2,
            "change_summary": {"changed": 1},
            "created_at": now,
            "activated_at": now,
            "documents": [
                {
                    "document_id": "document-1",
                    "document_version_id": "document-version-1",
                    "document_kind": "entity",
                    "document_key": "obsidian",
                    "file_path": "entities/obsidian.md",
                    "version": 1,
                    "title": "Obsidian",
                }
            ],
        }

    async def delete_wiki_document(
        self,
        user_id: str,
        *,
        document_id: str,
        source_event_id: str,
        occurred_at: object,
        memo: str | None,
    ) -> Mapping[str, object]:
        """알려진 문서만 soft-delete 결과로 반환한다."""
        from infrastructure.persistence.api import WikiDocumentNotFoundError

        if document_id != "document-1":
            raise WikiDocumentNotFoundError(document_id)
        return {
            "document_id": document_id,
            "document_kind": "entity",
            "document_key": "obsidian",
            "already_deleted": source_event_id == "delete-again",
            "unsearchable_chunk_count": 2,
        }

    @staticmethod
    def _summary() -> dict[str, object]:
        """목록과 상세가 공유하는 Wiki 문서 요약을 반환한다."""
        return {
            "document_id": "document-1",
            "document_version_id": "document-version-1",
            "document_kind": "entity",
            "document_key": "obsidian",
            "file_path": "entities/obsidian.md",
            "domain": "product",
            "title": "Obsidian",
            "summary": "지식 관리 도구",
            "version": 1,
            "source_count": 1,
            "updated_at": datetime(2026, 7, 16, tzinfo=UTC),
        }


def _client() -> TestClient:
    """가짜 Wiki 문서 Repository가 연결된 TestClient를 반환한다."""
    settings = Settings(environment="test")
    container = AppContainer(
        settings=settings,
        wiki_document_service=WikiDocumentService(_FakeWikiDocumentRepository()),
    )
    return TestClient(create_app(settings, container))


def test_wiki_document_list_detail_and_build_routes() -> None:
    """목록·Markdown 상세·Build Snapshot이 Swagger 계약으로 반환되는지 검증한다."""
    with _client() as client:
        listed = client.get(
            "/internal/v1/users/user-1/wiki/documents",
            params={"document_kind": "entity"},
        )
        detailed = client.get(
            "/internal/v1/users/user-1/wiki/documents/document-1"
        )
        build = client.get(
            "/internal/v1/users/user-1/wiki/versions/wiki-version-1"
        )

    assert listed.status_code == 200
    assert listed.json()["items"][0]["file_path"] == "entities/obsidian.md"
    assert detailed.status_code == 200
    assert detailed.json()["markdown"].endswith("# Obsidian")
    assert detailed.json()["sources"][0]["source_type"] == "web_clipping"
    assert build.status_code == 200
    assert build.json()["documents"][0]["document_version_id"] == (
        "document-version-1"
    )


def test_wiki_document_detail_hides_missing_document() -> None:
    """존재하지 않거나 다른 사용자의 문서가 안전한 404로 응답되는지 검증한다."""
    with _client() as client:
        response = client.get(
            "/internal/v1/users/user-1/wiki/documents/missing-document"
        )

    assert response.status_code == 404
    assert response.json()["code"] == "WIKI_DOCUMENT_NOT_FOUND"


def test_wiki_document_deletion_soft_deletes_and_is_idempotent() -> None:
    """삭제 요청이 soft-delete 결과를 반환하고 재요청이 멱등인지 검증한다."""
    with _client() as client:
        deleted = client.post(
            "/internal/v1/users/user-1/wiki-sources/deletions",
            json={"source_event_id": "delete-1", "document_id": "document-1"},
        )
        repeated = client.post(
            "/internal/v1/users/user-1/wiki-sources/deletions",
            json={"source_event_id": "delete-again", "document_id": "document-1"},
        )

    assert deleted.status_code == 200
    assert deleted.json()["document_key"] == "obsidian"
    assert deleted.json()["already_deleted"] is False
    assert deleted.json()["unsearchable_chunk_count"] == 2
    assert repeated.status_code == 200
    assert repeated.json()["already_deleted"] is True


def test_wiki_document_deletion_returns_404_for_unknown_document() -> None:
    """존재하지 않는 문서 삭제가 404 공통 오류를 반환하는지 검증한다."""
    with _client() as client:
        response = client.post(
            "/internal/v1/users/user-1/wiki-sources/deletions",
            json={"source_event_id": "delete-x", "document_id": "missing"},
        )

    assert response.status_code == 404
    assert response.json()["code"] == "WIKI_DOCUMENT_NOT_FOUND"
