"""활성 관심사와 개인 Wiki 연결 노드를 리포트 검색 범주로 구성한다."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from typing import Protocol


class ActiveInterestRequiredError(LookupError):
    """요청한 관심사가 현재 사용자의 활성·비차단 관심사가 아닌 오류."""


class InterestBundleRepository(Protocol):
    """INT-012가 활성 관심사와 Wiki 이웃을 읽는 저장소 경계."""

    async def load_active_interest(
        self, user_id: str, interest_id: str
    ) -> Mapping[str, object] | None:
        """사용자의 활성 Profile에 속한 비차단 관심사를 조회한다."""
        ...

    async def list_related_nodes(
        self,
        user_id: str,
        *,
        document_ids: Sequence[str],
        limit: int,
    ) -> Sequence[Mapping[str, object]]:
        """관심 근거 문서의 1홉 Wiki 이웃을 연결 강도 순으로 조회한다."""
        ...

    async def list_node_snapshots(
        self,
        user_id: str,
        *,
        document_ids: Sequence[str],
    ) -> Sequence[Mapping[str, object]]:
        """관심 근거 문서의 현재 Version과 요약을 입력 순서대로 조회한다."""
        ...


@dataclass(frozen=True, slots=True)
class InterestBundleNode:
    """Job 접수 시점에 고정한 개인 Wiki 노드 Version."""

    document_id: str
    document_version_id: str
    keyword: str
    document_kind: str
    summary: str
    aliases: tuple[str, ...]
    updated_at: str | None

    def to_payload(self) -> dict[str, object]:
        """비동기 Job에 저장할 JSON 호환 노드 Snapshot으로 변환한다."""
        return {
            "document_id": self.document_id,
            "document_version_id": self.document_version_id,
            "keyword": self.keyword,
            "document_kind": self.document_kind,
            "summary": self.summary,
            "aliases": list(self.aliases),
            "updated_at": self.updated_at,
        }


@dataclass(frozen=True, slots=True)
class InterestBundleNeighbor:
    """관심사 루트에서 1홉으로 연결된 검색 보조 노드."""

    document_id: str
    keyword: str
    document_kind: str
    weight: float
    relation_types: tuple[str, ...]
    shared_source_count: int
    degree: float
    document_version_id: str = ""
    summary: str = ""
    aliases: tuple[str, ...] = ()
    updated_at: str | None = None

    def to_payload(self) -> dict[str, object]:
        """비동기 Job에 저장할 JSON 호환 Payload로 변환한다."""
        return {
            "document_id": self.document_id,
            "keyword": self.keyword,
            "document_kind": self.document_kind,
            "weight": self.weight,
            "relation_types": list(self.relation_types),
            "shared_source_count": self.shared_source_count,
            "degree": self.degree,
            "document_version_id": self.document_version_id,
            "summary": self.summary,
            "aliases": list(self.aliases),
            "updated_at": self.updated_at,
        }


@dataclass(frozen=True, slots=True)
class InterestReportBundle:
    """활성 관심사 하나와 검색에 사용할 개인 Wiki 1홉 이웃 스냅샷."""

    profile_id: str
    profile_version: int
    interest_id: str
    root_keyword: str
    root_score: float
    root_document_ids: tuple[str, ...]
    root_documents: tuple[InterestBundleNode, ...]
    neighbors: tuple[InterestBundleNeighbor, ...]

    @property
    def keywords(self) -> tuple[str, ...]:
        """루트부터 시작하는 검색 키워드 목록을 반환한다."""
        return (self.root_keyword, *(neighbor.keyword for neighbor in self.neighbors))

    def to_payload(self) -> dict[str, object]:
        """Profile Version과 선택 결과를 보존할 JSON 호환 Payload로 변환한다."""
        return {
            "profile_id": self.profile_id,
            "profile_version": self.profile_version,
            "interest_id": self.interest_id,
            "root": {
                "keyword": self.root_keyword,
                "score": self.root_score,
                "document_ids": list(self.root_document_ids),
                "documents": [document.to_payload() for document in self.root_documents],
            },
            "neighbors": [neighbor.to_payload() for neighbor in self.neighbors],
            "keywords": list(self.keywords),
        }


# MVP: agent-api-mvp-scope.md에서 구현 대상으로 지정된 기능입니다.
async def int_012(
    repository: InterestBundleRepository,
    user_id: str,
    *,
    interest_id: str,
    neighbor_limit: int = 2,
) -> InterestReportBundle:
    """[INT-012] 활성 관심사와 Wiki 1홉 이웃을 리포트 검색 범주로 구성한다.

    Args:
        repository: 활성 관심사와 Wiki 이웃 조회 저장소
        user_id: 관심사 소유 사용자 ID
        interest_id: 현재 활성 Profile의 관심사 UUID
        neighbor_limit: 포함할 최대 1홉 이웃 수

    Returns:
        Profile Version에 고정된 관심사 범주 묶음

    Raises:
        ActiveInterestRequiredError: 관심사가 현재 활성·비차단 상태가 아닌 경우
        ValueError: 사용자·관심사 ID 또는 이웃 상한이 잘못된 경우
    """
    normalized_user_id = user_id.strip()
    normalized_interest_id = interest_id.strip()
    if not normalized_user_id:
        raise ValueError("INT-012에 user_id가 필요합니다.")
    if not normalized_interest_id:
        raise ValueError("INT-012에 interest_id가 필요합니다.")
    if not 0 <= neighbor_limit <= 10:
        raise ValueError("관심사 범주 이웃 상한은 0에서 10 사이여야 합니다.")

    active = await repository.load_active_interest(
        normalized_user_id, normalized_interest_id
    )
    if active is None:
        raise ActiveInterestRequiredError(normalized_interest_id)

    root_keyword = str(active.get("topic") or "").strip()
    if not root_keyword:
        raise ActiveInterestRequiredError(normalized_interest_id)
    document_ids = tuple(
        dict.fromkeys(
            str(document_id).strip()
            for document_id in (active.get("document_ids") or [])
            if str(document_id).strip()
        )
    )
    root_rows = (
        await repository.list_node_snapshots(
            normalized_user_id,
            document_ids=document_ids,
        )
        if document_ids
        else ()
    )
    root_documents = tuple(
        InterestBundleNode(
            document_id=str(item.get("document_id") or ""),
            document_version_id=str(item.get("document_version_id") or ""),
            keyword=str(item.get("keyword") or "").strip(),
            document_kind=str(item.get("document_kind") or ""),
            summary=str(item.get("summary") or "").strip(),
            aliases=tuple(str(value) for value in item.get("aliases") or ()),
            updated_at=(
                str(item["updated_at"])
                if item.get("updated_at") is not None
                else None
            ),
        )
        for item in root_rows
        if str(item.get("document_id") or "").strip()
        and str(item.get("document_version_id") or "").strip()
    )
    related = (
        await repository.list_related_nodes(
            normalized_user_id,
            document_ids=document_ids,
            limit=neighbor_limit,
        )
        if document_ids and neighbor_limit > 0
        else ()
    )
    neighbors = tuple(
        InterestBundleNeighbor(
            document_id=str(item.get("document_id") or ""),
            keyword=str(item.get("keyword") or "").strip(),
            document_kind=str(item.get("document_kind") or ""),
            weight=float(item.get("weight") or 0.0),
            relation_types=tuple(str(value) for value in item.get("relation_types") or ()),
            shared_source_count=int(item.get("shared_source_count") or 0),
            degree=float(item.get("degree") or 0.0),
            document_version_id=str(item.get("document_version_id") or ""),
            summary=str(item.get("summary") or "").strip(),
            aliases=tuple(str(value) for value in item.get("aliases") or ()),
            updated_at=(
                str(item["updated_at"])
                if item.get("updated_at") is not None
                else None
            ),
        )
        for item in related
        if str(item.get("document_id") or "").strip()
        and str(item.get("keyword") or "").strip()
    )
    return InterestReportBundle(
        profile_id=str(active["profile_id"]),
        profile_version=int(active["profile_version"]),
        interest_id=normalized_interest_id,
        root_keyword=root_keyword,
        root_score=float(active.get("score") or 0.0),
        root_document_ids=document_ids,
        root_documents=root_documents,
        neighbors=neighbors,
    )
