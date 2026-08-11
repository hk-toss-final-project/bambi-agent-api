"""Global 수집 캐시 조회 경계 (비서 전용, 동기).

Global 뉴스 파이프라인(global_content_fetcher)이 Jina Reader로 수집해 둔 기사
본문을 비서가 재사용한다. 소스 커버리지 통합으로 두 파이프라인이 같은 기사를
보게 되면서, 본문이 이미 캐시에 있으면 짧은 Provider 설명 대신 전체 본문을
유사도 필터·통합 요약 입력으로 쓸 수 있다 — 추가 네트워크 호출 없이.

비서는 DB 없이도 동작해야 하므로(이력 저장소 storage.py와 같은 원칙) 연결
문자열이 없거나 조회가 실패하면 빈 결과로 폴백한다. 수집 캐시
(`global_source_documents`)는 소유자가 없는 공유 데이터라 RLS 정책상 접근
Scope 설정 없이 SELECT가 허용된다.
"""

from __future__ import annotations

import logging
import os
from collections.abc import Sequence
from typing import TypedDict

logger = logging.getLogger("agent.assistant.content_store")


class CachedArticleAsset(TypedDict):
    """비서가 재사용하는 Global 기사 본문과 대표 이미지다."""

    markdown: str
    image_url: str | None


def fetch_global_article_assets(
    urls: Sequence[str],
) -> dict[str, CachedArticleAsset]:
    """canonical_url이 일치하는 fetched 캐시 기사 자산을 일괄 조회한다.

    Args:
        urls: 조회할 기사 URL 목록 (Provider가 준 원본 URL 그대로)

    Returns:
        {기사 URL: 본문·대표 이미지}. 본문이 없거나 조회가 불가능하면 해당 키 없음.
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
                SELECT canonical_url, markdown, image_url
                FROM agent.global_source_documents
                WHERE content_status = 'fetched'
                  AND markdown IS NOT NULL
                  AND canonical_url = ANY(%s)
                """,
                (targets,),
            )
            return {
                str(canonical_url): {
                    "markdown": str(content),
                    "image_url": str(image_url) if image_url else None,
                }
                for canonical_url, content, image_url in cursor.fetchall()
                if content
            }
    except Exception as error:
        logger.warning(
            "Global 캐시 본문 조회 실패, Provider 설명 스니펫으로 계속한다: %s: %s",
            type(error).__name__,
            error,
        )
        return {}
