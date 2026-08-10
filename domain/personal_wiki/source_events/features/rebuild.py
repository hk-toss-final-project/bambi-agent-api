"""개인 Wiki 재구성 요청 수신 기능 구현."""

from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class WikiRebuildRequest:
    """검증된 개인 Wiki 재구성 요청."""

    source_document_version_id: str


async def wse_010(source_document_version_id: str) -> WikiRebuildRequest:
    """[WSE-010] Wiki 재구성 요청 수신.

    사용자의 개인 Wiki 재구성 요청을 수신한다. 실제 Job 등록은 저장소
    계층(`enqueue_wiki_rebuild_for_source`)이 담당하며, 여기서는 요청 형태만
    검증·정규화한다.
    """
    normalized = source_document_version_id.strip()
    if not normalized:
        raise ValueError("WSE-010에는 source_document_version_id가 필요합니다.")
    return WikiRebuildRequest(source_document_version_id=normalized)
