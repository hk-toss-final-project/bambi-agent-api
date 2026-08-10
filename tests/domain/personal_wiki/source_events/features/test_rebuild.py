"""WSE-010 개인 Wiki 재구성 요청 검증을 확인한다."""

import asyncio

import pytest

from domain.personal_wiki.source_events.api import WikiRebuildRequest, wse_010


def test_wse_010_normalizes_and_validates_source_document_version_id() -> None:
    """앞뒤 공백을 제거하고 유효한 요청을 반환하는지 검증한다."""
    request = asyncio.run(wse_010("  source-version-1  "))

    assert request == WikiRebuildRequest(source_document_version_id="source-version-1")


def test_wse_010_rejects_blank_source_document_version_id() -> None:
    """공백뿐인 source_document_version_id를 거부하는지 검증한다."""
    with pytest.raises(ValueError):
        asyncio.run(wse_010("   "))
