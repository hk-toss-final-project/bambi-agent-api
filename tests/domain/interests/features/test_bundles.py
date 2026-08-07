"""활성 관심사 범주 묶음(INT-012) 도메인 기능을 검증한다."""

import asyncio
from collections.abc import Mapping, Sequence

import pytest

from domain.interests.api import ActiveInterestRequiredError, int_012


class _Repository:
    """활성 관심사와 Wiki 이웃을 고정 응답으로 제공하는 저장소 대역."""

    def __init__(
        self,
        *,
        active: Mapping[str, object] | None,
        related: Sequence[Mapping[str, object]] = (),
    ) -> None:
        """테스트 응답과 마지막 이웃 조회 인자를 보관한다."""
        self.active = active
        self.related = related
        self.related_call: tuple[str, tuple[str, ...], int] | None = None

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
        related=[
            {
                "document_id": "doc-neighbor",
                "keyword": "코스닥시장",
                "document_kind": "entity",
                "weight": 1.0,
                "relation_types": ["entity_relation"],
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
    assert bundle.keywords == ("코스피", "코스닥시장")
    assert repository.related_call == ("user-1", ("doc-root",), 2)
    assert bundle.to_payload()["keywords"] == ["코스피", "코스닥시장"]


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
    assert bundle.neighbors == ()
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
