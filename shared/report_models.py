"""Report Builder 생성 경계에서 공유하는 순수 데이터 구조.

검색(infrastructure)이 만들고 생성(agent)이 소비하는 Context 문서와,
생성이 만들고 영속화(infrastructure)가 소비하는 결과를 정의해 두 계층이
서로를 import하지 않게 한다.
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class ReportContextDocument:
    """Report Builder 생성에 전달할 개인·Global 검색 문서 Chunk."""

    reference: str
    document_version_id: str
    chunk_id: str
    namespace_key: str
    title: str
    content: str
    url: str | None
    score: float


@dataclass(frozen=True, slots=True)
class GeneratedReportContent:
    """검증된 Report Builder 제목·요약·본문과 사용한 문서 참조."""

    title: str
    summary: str
    body: str
    citation_references: tuple[str, ...]
    # [REPORT-010] 생성된 내용에서 뽑은 검색·추천용 태그. 생성 요청 topic과는
    # 분리해 보존한다 — 요청 주제와 실제 작성된 내용이 갈리기 때문이다
    # (실측: '의존성 구조' 요청이 강한 결합·DDD·Application Layer를 다뤘다).
    # 보조 정보라 비어 있어도 생성은 성공한다.
    content_tags: tuple[str, ...] = ()
