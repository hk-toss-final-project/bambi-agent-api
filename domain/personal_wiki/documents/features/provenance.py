"""개인 Wiki 문서 Version과 원본 Version 출처 연결 기능 구현."""

from typing import Any

from psycopg import AsyncConnection


# MVP: agent-api-mvp-scope.md에서 구현 대상으로 지정된 기능입니다.
async def pwiki_007(
    connection: AsyncConnection[dict[str, Any]],
    *,
    wiki_document_version_id: object,
    source_document_version_id: str,
    namespace_key: str,
) -> None:
    """[PWIKI-007] Wiki 문서 출처 추적.

    클리핑, URL, 위키마킹 등 문서 유입 경로를 기록한다.
    """
    await connection.execute(
        """
        INSERT INTO agent.wiki_document_sources (
            wiki_document_version_id,
            source_document_version_id,
            namespace_key,
            relation_type
        ) VALUES (%s, %s, %s, 'source')
        ON CONFLICT DO NOTHING
        """,
        (wiki_document_version_id, source_document_version_id, namespace_key),
    )
