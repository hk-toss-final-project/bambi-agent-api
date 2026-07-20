"""Bambi 생성 경계에서 공유하는 순수 데이터 구조.

검색(infrastructure)이 만들고 생성(agent)이 소비하는 Context 문서와,
생성이 만들고 영속화(infrastructure)가 소비하는 결과를 정의해 두 계층이
서로를 import하지 않게 한다.
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class BambiContextDocument:
    """Bambi 생성에 전달할 개인·Global 검색 문서 Chunk."""

    reference: str
    document_version_id: str
    chunk_id: str
    namespace_key: str
    title: str
    content: str
    url: str | None
    score: float


@dataclass(frozen=True, slots=True)
class GeneratedBambiContent:
    """검증된 Bambi 제목·요약·본문과 사용한 문서 참조."""

    title: str
    summary: str
    body: str
    citation_references: tuple[str, ...]
