"""Agent Job 생성·조회·진행률·결과 기능의 typed 계약을 검증한다."""

import asyncio

import pytest

from domain.jobs.features.idempotency import job_010
from domain.jobs.features.lifecycle import job_001, job_002
from domain.jobs.features.progress import job_006
from domain.jobs.features.results import job_007


class _FakeJobReader:
    """Job 조회 호출을 기록하는 저장소 대역."""

    def __init__(self) -> None:
        self.requested_job_id: str | None = None

    async def get_job(self, job_id: str) -> dict[str, str]:
        """요청된 Job ID를 기록하고 고정 Row를 반환한다."""
        self.requested_job_id = job_id
        return {"id": job_id}


def test_job_001_builds_creation_with_shared_idempotency_rule() -> None:
    """Job 생성 값과 공통 멱등성 Key를 하나의 typed 결과로 만든다."""
    creation = asyncio.run(
        job_001(
            feature_id="SVC-002",
            job_type="personal_wiki_build",
            user_id="user-1",
            idempotency_parts=[" user-1 ", "source-1"],
            payload={"source_document_id": "source-1"},
            request_id="request-1",
        )
    )

    assert creation.idempotency_key == "user-1:source-1"
    assert creation.payload == {"source_document_id": "source-1"}


def test_job_002_uses_explicit_reader_dependency() -> None:
    """Job 조회 기능이 주입된 Reader 경계를 통해 한 번 조회한다."""
    reader = _FakeJobReader()

    result = asyncio.run(job_002(reader, "job-1"))

    assert result == {"id": "job-1"}
    assert reader.requested_job_id == "job-1"


def test_job_progress_and_idempotency_reject_invalid_transitions() -> None:
    """빈 멱등성 구성 값과 진행률 역행을 거부한다."""
    with pytest.raises(ValueError, match="비어"):
        asyncio.run(job_010(["user-1", " "]))

    with pytest.raises(ValueError, match="작아질"):
        asyncio.run(job_006(80, 50))

    assert asyncio.run(job_006(5, 100)) == 100


def test_job_007_returns_a_detached_result_mapping() -> None:
    """완료 결과를 변경 가능한 독립 사전으로 정규화한다."""
    source = {"wiki_version_id": "wiki-1"}

    result = asyncio.run(job_007(source))

    assert result == source
    assert result is not source
