"""활성 관심사 범주 묶음(INT-012) 도메인 기능을 검증한다."""

import asyncio
from collections.abc import Mapping, Sequence

import pytest

from domain.interests.api import ActiveInterestRequiredError, int_012, int_013


class _Repository:
    """활성 관심사와 Wiki 이웃을 고정 응답으로 제공하는 저장소 대역."""

    def __init__(
        self,
        *,
        active: Mapping[str, object] | None,
        snapshots: Sequence[Mapping[str, object]] = (),
        related: Sequence[Mapping[str, object]] = (),
        matched_interest_id: str | None = None,
    ) -> None:
        """테스트 응답과 마지막 이웃 조회 인자를 보관한다."""
        self.active = active
        self.snapshots = snapshots
        self.related = related
        self.matched_interest_id = matched_interest_id
        self.snapshot_call: tuple[str, tuple[str, ...]] | None = None
        self.related_call: tuple[str, tuple[str, ...], int] | None = None
        self.match_call: tuple[str, str] | None = None

    async def load_active_interest(
        self, user_id: str, interest_id: str
    ) -> Mapping[str, object] | None:
        """설정한 활성 관심사 응답을 반환한다."""
        return self.active

    async def list_related_nodes(
        self,
        user_id: str,
        *,
        document_ids: Sequence[str],
        limit: int,
    ) -> Sequence[Mapping[str, object]]:
        """호출 인자를 기록하고 설정한 Wiki 이웃을 반환한다."""
        self.related_call = (user_id, tuple(document_ids), limit)
        return self.related

    async def list_node_snapshots(
        self,
        user_id: str,
        *,
        document_ids: Sequence[str],
    ) -> Sequence[Mapping[str, object]]:
        """호출 인자를 기록하고 설정한 루트 Wiki Snapshot을 반환한다."""
        self.snapshot_call = (user_id, tuple(document_ids))
        return self.snapshots

    async def find_active_interest_id(
        self, user_id: str, topic: str
    ) -> str | None:
        """호출 인자를 기록하고 설정한 매칭 관심사 ID를 반환한다."""
        self.match_call = (user_id, topic)
        return self.matched_interest_id


def _active_interest() -> dict[str, object]:
    """활성 관심사 예시 Row를 만든다."""
    return {
        "profile_id": "profile-1",
        "profile_version": 4,
        "topic": "코스피",
        "score": 0.91,
        "document_ids": ["doc-root", "doc-root"],
    }


def test_int_012_builds_versioned_bundle_from_evidence_documents() -> None:
    """관심 근거 문서에서 읽은 이웃과 Profile Version을 스냅샷으로 묶는다."""
    repository = _Repository(
        active=_active_interest(),
        snapshots=[
            {
                "document_id": "doc-root",
                "document_version_id": "version-root",
                "keyword": "코스피",
                "document_kind": "concept",
                "summary": "한국 주식시장의 대표 지수",
                "aliases": ["KOSPI"],
                "updated_at": "2026-08-09T10:00:00+00:00",
            }
        ],
        related=[
            {
                "document_id": "doc-neighbor",
                "document_version_id": "version-neighbor",
                "keyword": "코스닥시장",
                "document_kind": "entity",
                "summary": "성장 기업 중심 시장",
                "aliases": ["KOSDAQ"],
                "updated_at": "2026-08-08T10:00:00+00:00",
                "weight": 1.0,
                "relation_types": ["entity_relation"],
                "relations": [
                    {
                        "relation_id": "relation-1",
                        "root_document_id": "doc-root",
                        "direction": "root_to_neighbor",
                        "relation_type": "entity_relation",
                        "confidence": 0.94,
                        "provenance_kind": "source_explicit",
                        "review_status": "accepted",
                        "rationale": "두 시장을 함께 비교한다.",
                        "supports": [
                            {
                                "source_document_version_id": "source-version-1",
                                "provenance_kind": "source_explicit",
                                "confidence": 0.94,
                                "review_status": "accepted",
                                "evidence": "코스피와 코스닥이 동반 하락했다.",
                                "rationale": "같은 시장 흐름의 근거",
                            }
                        ],
                    }
                ],
                "shared_source_count": 2,
                "degree": 3.0,
            }
        ],
    )

    bundle = asyncio.run(
        int_012(repository, "user-1", interest_id="interest-1", neighbor_limit=2)
    )

    assert bundle.profile_id == "profile-1"
    assert bundle.profile_version == 4
    assert bundle.interest_id == "interest-1"
    assert bundle.root_document_ids == ("doc-root",)
    assert bundle.root_documents[0].document_version_id == "version-root"
    assert bundle.root_documents[0].aliases == ("KOSPI",)
    assert bundle.neighbors[0].document_version_id == "version-neighbor"
    assert bundle.neighbors[0].relations[0].direction == "root_to_neighbor"
    assert bundle.neighbors[0].relations[0].supports[0].evidence.startswith("코스피")
    assert bundle.keywords == ("코스피", "코스닥시장")
    assert repository.snapshot_call == ("user-1", ("doc-root",))
    assert repository.related_call == ("user-1", ("doc-root",), 2)
    payload = bundle.to_payload()
    assert payload["keywords"] == ["코스피", "코스닥시장"]
    assert payload["root"]["documents"][0]["document_version_id"] == "version-root"
    assert payload["neighbors"][0]["relations"][0]["confidence"] == 0.94


def test_int_012_drops_relation_without_active_support_payload() -> None:
    """근거가 없는 관계는 저장소가 잘못 반환해도 Bundle Context에서 제외한다."""
    repository = _Repository(
        active=_active_interest(),
        related=[
            {
                "document_id": "doc-neighbor",
                "keyword": "코스닥시장",
                "document_kind": "entity",
                "relation_types": ["associated_with"],
                "relations": [
                    {
                        "relation_id": "unsupported",
                        "direction": "root_to_neighbor",
                        "relation_type": "associated_with",
                        "supports": [],
                    }
                ],
            }
        ],
    )

    bundle = asyncio.run(int_012(repository, "user-1", interest_id="interest-1"))

    assert bundle.neighbors[0].relations == ()


def test_int_012_rejects_interest_outside_active_profile() -> None:
    """현재 활성·비차단 관심사를 찾지 못하면 범주 생성을 거절한다."""
    repository = _Repository(active=None)

    with pytest.raises(ActiveInterestRequiredError):
        asyncio.run(int_012(repository, "user-1", interest_id="retired-interest"))


def test_int_012_keeps_isolated_interest_as_root_only_bundle() -> None:
    """근거 문서나 이웃이 없는 관심사도 루트 단일 범주로 안전하게 폴백한다."""
    active = _active_interest()
    active["document_ids"] = []
    repository = _Repository(active=active)

    bundle = asyncio.run(int_012(repository, "user-1", interest_id="interest-1"))

    assert bundle.keywords == ("코스피",)
    assert bundle.root_documents == ()
    assert bundle.neighbors == ()
    assert repository.snapshot_call is None
    assert repository.related_call is None


@pytest.mark.parametrize("limit", [-1, 11])
def test_int_012_validates_neighbor_limit(limit: int) -> None:
    """비용 상한을 벗어난 이웃 개수는 DB 조회 전에 거절한다."""
    repository = _Repository(active=_active_interest())

    with pytest.raises(ValueError, match="상한"):
        asyncio.run(
            int_012(
                repository,
                "user-1",
                interest_id="interest-1",
                neighbor_limit=limit,
            )
        )


def test_int_013_returns_matched_active_interest_id() -> None:
    """주제 문자열이 활성 관심사와 일치하면 그 관심사 ID를 반환한다."""
    repository = _Repository(active=None, matched_interest_id="interest-1")

    interest_id = asyncio.run(int_013(repository, "user-1", "코스피"))

    assert interest_id == "interest-1"
    assert repository.match_call == ("user-1", "코스피")


def test_int_013_returns_none_when_no_active_interest_matches() -> None:
    """일치하는 활성 관심사가 없으면 None을 반환한다."""
    repository = _Repository(active=None, matched_interest_id=None)

    interest_id = asyncio.run(int_013(repository, "user-1", "환율"))

    assert interest_id is None


@pytest.mark.parametrize(
    ("user_id", "topic"), [("", "코스피"), ("user-1", ""), (" ", " ")]
)
def test_int_013_rejects_blank_arguments(user_id: str, topic: str) -> None:
    """user_id·topic이 비어 있으면 저장소를 조회하지 않고 거절한다."""
    repository = _Repository(active=None, matched_interest_id="interest-1")

    with pytest.raises(ValueError):
        asyncio.run(int_013(repository, user_id, topic))

    assert repository.match_call is None
