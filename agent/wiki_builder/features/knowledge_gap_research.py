"""Personal Wiki V3 지식 공백을 기존 URL 수집·쓰기 루프로 연결한다.

의미 감사의 제한된 검색 질의를 기존 Live 수집기에 전달하고, 공개 HTTP(S)
결과만 멱등 Source Event로 등록한다. 외부 본문은 유지 루프가 Wiki에 직접 쓰지
않으며 personal_wiki_url 수집 Job과 후속 쓰기 루프의 검증 경계를 그대로 탄다.
"""

from __future__ import annotations

import hashlib
import ipaddress
from asyncio import to_thread
from collections.abc import Awaitable, Callable, Sequence
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any
from urllib.parse import urlsplit, urlunsplit

from psycopg import AsyncConnection

from agent.report_builder.api import collect_live_context
from infrastructure.persistence.api import (
    PersistedSourceSubmission,
    register_url_and_enqueue,
    set_personal_wiki_scope,
)
from shared.report_models import ReportContextDocument

from .semantic_audit import WikiSemanticIssue, WikiSemanticIssueCode

type DictRow = dict[str, Any]
type WikiKnowledgeCollector = Callable[..., Sequence[ReportContextDocument]]
type WikiUrlRegistrar = Callable[..., Awaitable[PersistedSourceSubmission]]


@dataclass(frozen=True, slots=True)
class WikiKnowledgeGapResearchLimits:
    """한 유지 Job이 사용할 외부 조사 질의·문서·URL 상한."""

    query_limit: int = 2
    documents_per_query: int = 5
    url_limit: int = 3


@dataclass(frozen=True, slots=True)
class WikiKnowledgeGapResearchResult:
    """외부 조사와 쓰기 루프 등록 집계 및 원문 없는 경고."""

    query_count: int
    collected_document_count: int
    queued_source_count: int
    source_event_ids: tuple[str, ...]
    warnings: tuple[str, ...]


def _validate_limits(limits: WikiKnowledgeGapResearchLimits) -> None:
    """외부 조사 상한이 음수가 아닌지 검증한다."""
    for name, value in (
        ("query_limit", limits.query_limit),
        ("documents_per_query", limits.documents_per_query),
        ("url_limit", limits.url_limit),
    ):
        if value < 0:
            raise ValueError(f"{name}은 0 이상이어야 합니다.")


def _public_url(value: str | None) -> str | None:
    """공개 HTTP(S) URL을 fragment 없는 안정적인 등록 값으로 정규화한다."""
    if not value:
        return None
    parsed = urlsplit(value.strip())
    if (
        parsed.scheme.lower() not in {"http", "https"}
        or not parsed.hostname
        or parsed.username is not None
        or parsed.password is not None
    ):
        return None
    hostname = parsed.hostname.casefold().rstrip(".")
    if hostname == "localhost" or hostname.endswith(".local"):
        return None
    try:
        address = ipaddress.ip_address(hostname)
    except ValueError:
        address = None
    if address is not None and not address.is_global:
        return None
    try:
        port = parsed.port
    except ValueError:
        return None
    netloc = f"[{hostname}]" if ":" in hostname else hostname
    if port is not None:
        netloc = f"{netloc}:{port}"
    return urlunsplit(
        (
            parsed.scheme.lower(),
            netloc,
            parsed.path or "/",
            parsed.query,
            "",
        )
    )


def _source_event_id(issue_id: str, url: str) -> str:
    """같은 의미 문제와 URL 조합에 재실행해도 같은 Source Event ID를 만든다."""
    digest = hashlib.sha256(url.encode("utf-8")).hexdigest()[:16]
    return f"wiki-v3:{issue_id}:{digest}"


def _knowledge_gap_issues(
    issues: Sequence[WikiSemanticIssue],
    *,
    limit: int,
) -> tuple[WikiSemanticIssue, ...]:
    """검색 질의가 있는 지식 공백을 문제 ID 순서와 상한으로 고른다."""
    return tuple(
        sorted(
            (
                issue
                for issue in issues
                if issue.code is WikiSemanticIssueCode.KNOWLEDGE_GAP
                and issue.research_query
            ),
            key=lambda issue: issue.issue_id,
        )[:limit]
    )


async def research_wiki_knowledge_gaps(
    connection: AsyncConnection[DictRow],
    *,
    user_id: str,
    job_id: str,
    issues: Sequence[WikiSemanticIssue],
    model: str,
    limits: WikiKnowledgeGapResearchLimits = WikiKnowledgeGapResearchLimits(),
    collector: WikiKnowledgeCollector = collect_live_context,
    registrar: WikiUrlRegistrar = register_url_and_enqueue,
) -> WikiKnowledgeGapResearchResult:
    """지식 공백의 공개 URL을 기존 수집·쓰기 Job으로 멱등 등록한다."""
    _validate_limits(limits)
    selected_issues = _knowledge_gap_issues(issues, limit=limits.query_limit)
    warnings: list[str] = []
    candidates: list[tuple[WikiSemanticIssue, str]] = []
    query_count = 0
    collected_count = 0
    seen_urls: set[str] = set()

    for issue in selected_issues:
        query_count += 1
        try:
            documents = await to_thread(
                collector,
                issue.research_query,
                user_id,
                model=model,
                related_keywords=(),
            )
        except Exception as error:  # noqa: BLE001 - 다른 지식 공백은 계속 조사함
            warnings.append(
                f"{issue.issue_id}: 외부 수집 실패({type(error).__name__})"
            )
            continue
        selected_documents = list(documents)[: limits.documents_per_query]
        collected_count += len(selected_documents)
        for document in selected_documents:
            url = _public_url(document.url)
            if url is None or url in seen_urls:
                continue
            seen_urls.add(url)
            candidates.append((issue, url))
            if len(candidates) >= limits.url_limit:
                break
        if len(candidates) >= limits.url_limit:
            break

    source_event_ids: list[str] = []
    for issue, url in candidates:
        source_event_id = _source_event_id(issue.issue_id, url)
        try:
            async with connection.transaction():
                await set_personal_wiki_scope(connection, user_id=user_id)
                await registrar(
                    connection,
                    user_id=user_id,
                    source_event_id=source_event_id,
                    url=url,
                    occurred_at=datetime.now(UTC),
                    memo=f"Wiki V3 지식 공백 {issue.issue_id}",
                    request_id=f"wiki-maintenance:{job_id}",
                )
        except Exception as error:  # noqa: BLE001 - URL별 독립 실패로 나머지 계속 등록
            warnings.append(
                f"{issue.issue_id}: URL 등록 실패({type(error).__name__})"
            )
            continue
        source_event_ids.append(source_event_id)

    return WikiKnowledgeGapResearchResult(
        query_count=query_count,
        collected_document_count=collected_count,
        queued_source_count=len(source_event_ids),
        source_event_ids=tuple(source_event_ids),
        warnings=tuple(warnings),
    )


__all__ = [
    "WikiKnowledgeGapResearchLimits",
    "WikiKnowledgeGapResearchResult",
    "research_wiki_knowledge_gaps",
]
