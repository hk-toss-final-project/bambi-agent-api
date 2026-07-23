"""Global 본문 저장소 조회 경계 (비서 전용, 동기).

Global 뉴스 파이프라인(global_content_fetcher)이 Jina Reader로 수집해 둔 기사
본문을 비서가 재사용한다. 소스 커버리지 통합으로 두 파이프라인이 같은 기사를
보게 되면서, 본문이 이미 저장돼 있으면 짧은 Provider 설명 대신 전체 본문을
유사도 필터·통합 요약 입력으로 쓸 수 있다 — 추가 네트워크 호출 없이.

비서는 DB 없이도 동작해야 하므로(이력 저장소 storage.py와 같은 원칙) 연결
문자열이 없거나 조회가 실패하면 빈 결과로 폴백한다. Global 문서 SELECT는
RLS 정책상 접근 Scope 설정 없이 허용된다(wiki_document_read).
"""

from __future__ import annotations

import logging
import os
from collections.abc import Sequence

logger = logging.getLogger("agent.assistant.content_store")


def fetch_global_article_texts(urls: Sequence[str]) -> dict[str, str]:
    """canonical_url이 일치하는 fetched Global 문서의 본문을 일괄 조회한다.

    Args:
        urls: 조회할 기사 URL 목록 (Provider가 준 원본 URL 그대로)

    Returns:
        {기사 URL: 본문 Markdown}. 본문이 없거나 조회가 불가능하면 해당 키 없음.
    """
    targets = [url for url in urls if url]
    dsn = os.environ.get("AGENT_DATABASE_URL")
    if not dsn or not targets:
        return {}
    try:
        import psycopg

        with psycopg.connect(dsn) as connection, connection.cursor() as cursor:
            cursor.execute(
                """
                SELECT document.canonical_url, version.normalized_content
                FROM agent.wiki_documents AS document
                JOIN agent.wiki_document_versions AS version
                  ON version.document_id = document.id
                 AND version.namespace_key = document.namespace_key
                 AND version.version = document.current_version
                WHERE document.namespace_key = 'global'
                  AND document.deleted_at IS NULL
                  AND document.metadata->>'content_status' = 'fetched'
                  AND document.canonical_url = ANY(%s)
                """,
                (targets,),
            )
            return {
                str(canonical_url): str(content)
                for canonical_url, content in cursor.fetchall()
                if content
            }
    except Exception as error:
        logger.warning(
            "Global 본문 조회 실패, Provider 설명 스니펫으로 계속한다: %s: %s",
            type(error).__name__,
            error,
        )
        return {}
