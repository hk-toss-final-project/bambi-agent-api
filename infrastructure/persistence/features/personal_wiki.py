"""기능 구현 모듈.

DB-002, DB-003, DB-004, DB-005, DB-006, DB-007 기능의 실제 구현 위치를 제공한다.
"""

from dataclasses import dataclass, field
from datetime import date, datetime
from typing import Any

from psycopg import AsyncConnection

from shared.contracts import FeatureRequest, FeatureResult

type DictRow = dict[str, Any]


# MVP: agent-api-mvp-scope.md에서 구현 대상으로 지정된 기능입니다.
async def db_002(request: FeatureRequest) -> FeatureResult:
    """[DB-002] Wiki Source Event 저장.

    개인 Wiki 반영의 근거가 되는 이벤트를 저장한다.
    """
    raise NotImplementedError("[DB-002] 기능 구현이 필요합니다.")


# MVP: agent-api-mvp-scope.md에서 구현 대상으로 지정된 기능입니다.
async def db_003(request: FeatureRequest) -> FeatureResult:
    """[DB-003] 개인 Wiki 문서 저장.

    사용자별 Wiki 문서와 버전을 저장한다.
    """
    raise NotImplementedError("[DB-003] 기능 구현이 필요합니다.")


# MVP: agent-api-mvp-scope.md에서 구현 대상으로 지정된 기능입니다.
async def db_004(request: FeatureRequest) -> FeatureResult:
    """[DB-004] 개인 Wiki Chunk 저장.

    개인 Wiki 검색용 Chunk를 저장한다.
    """
    raise NotImplementedError("[DB-004] 기능 구현이 필요합니다.")


# MVP: agent-api-mvp-scope.md에서 구현 대상으로 지정된 기능입니다.
async def db_005(request: FeatureRequest) -> FeatureResult:
    """[DB-005] 개인 Wiki Embedding 저장.

    개인 Wiki의 Vector 데이터를 저장한다.
    """
    raise NotImplementedError("[DB-005] 기능 구현이 필요합니다.")


async def db_006(request: FeatureRequest) -> FeatureResult:
    """[DB-006] 개인 Wiki Version 저장.

    개인 Wiki 재구성 버전을 저장한다.
    """
    raise NotImplementedError("[DB-006] 기능 구현이 필요합니다.")


async def db_007(request: FeatureRequest) -> FeatureResult:
    """[DB-007] 사용자 관심사 저장.

    관심사 프로필, 계층, 관계를 저장한다.
    """
    raise NotImplementedError("[DB-007] 기능 구현이 필요합니다.")


@dataclass(frozen=True, slots=True)
class UserSourceDocumentForAgent:
    """WBA-001/WBA-003이 그대로 읽어 쓸 수 있는 사용자 원본 문서 Version 데이터."""

    source_document_id: str
    source_document_version_id: str
    user_id: str
    namespace_key: str
    source_type: str
    canonical_url: str | None
    version: int
    title: str
    author: str | None
    published_at: datetime | None
    clipped_on: date | None
    description: str | None
    tags: list[str] = field(default_factory=list)
    raw_content: str | None = None
    content_format: str = "markdown"
    object_uri: str | None = None
    source_metadata: dict[str, Any] = field(default_factory=dict)


async def get_user_source_document_version_for_agent(
    connection: AsyncConnection[DictRow],
    *,
    user_id: str,
    source_document_version_id: str,
) -> UserSourceDocumentForAgent | None:
    """Personal Wiki Builder Agent가 읽을 사용자 원본 Version을 PostgreSQL에서 조회한다.

    user_source_document_versions의 Frontmatter·Markdown 원문과 user_source_documents의
    소유자·canonical_url을 한 Row로 결합해 반환한다. WBA-001이 Job에 담긴
    source_document_version_id로 이 Version만 증분 로드하고, WBA-003이 반환된 데이터를
    그대로 정규화 입력으로 사용한다. 호출 전 Connection Transaction에 RLS를 위한
    `app.user_id`, `app.access_scope`를 `SET LOCAL`로 지정해야 한다.
    """
    cursor = await connection.execute(
        """
        SELECT
            document.id AS source_document_id,
            document.user_id,
            document.namespace_key,
            document.source_type,
            document.canonical_url,
            version.id AS source_document_version_id,
            version.version,
            version.title,
            version.author,
            version.published_at,
            version.clipped_on,
            version.description,
            version.tags,
            version.raw_content,
            version.content_format,
            version.object_uri,
            version.source_metadata
        FROM agent.user_source_document_versions AS version
        JOIN agent.user_source_documents AS document
          ON document.id = version.source_document_id
         AND document.namespace_key = version.namespace_key
        WHERE version.id = %s
          AND document.user_id = %s
          AND document.deleted_at IS NULL
        """,
        (source_document_version_id, user_id),
    )
    row = await cursor.fetchone()
    if row is None:
        return None
    return UserSourceDocumentForAgent(
        source_document_id=str(row["source_document_id"]),
        source_document_version_id=str(row["source_document_version_id"]),
        user_id=row["user_id"],
        namespace_key=row["namespace_key"],
        source_type=row["source_type"],
        canonical_url=row["canonical_url"],
        version=row["version"],
        title=row["title"],
        author=row["author"],
        published_at=row["published_at"],
        clipped_on=row["clipped_on"],
        description=row["description"],
        tags=list(row["tags"] or []),
        raw_content=row["raw_content"],
        content_format=row["content_format"],
        object_uri=row["object_uri"],
        source_metadata=dict(row["source_metadata"] or {}),
    )
