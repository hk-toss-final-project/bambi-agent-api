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
    # 고정 Wiki 노드, 일반 검색, Global/Live 등 Context의 생성 역할.
    context_role: str = "retrieved"
    # 개인 Wiki 지식이 어느 시점 기준인지 생성기와 실행 추적에 전달한다.
    source_updated_at: str | None = None
    # 원문에서 수집한 대표 이미지. 리포트가 실제로 인용한 문서만 상단 후보가 된다.
    image_url: str | None = None


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
