"""개인 Wiki 문서 기반 관심 키워드 추출 규칙을 검증한다."""

from agent.wiki_builder.api import extract_interest_candidates


def test_extract_interest_candidates_prioritizes_titles_and_shared_topics() -> None:
    """문서 제목과 여러 문서에 반복된 Topic이 높은 점수와 근거를 갖는지 검증한다."""
    candidates = extract_interest_candidates(
        [
            {
                "document_id": "doc-1",
                "title": "Obsidian",
                "summary": "Markdown 기반 연결 노트 지식 관리 도구",
                "domain": "product",
                "source_metadata": {"aliases": ["옵시디언"], "tags": ["Markdown"]},
            },
            {
                "document_id": "doc-2",
                "title": "Markdown 연결 노트",
                "summary": "Obsidian에서 Markdown 문서를 연결하는 방법",
                "domain": "method",
                "source_metadata": {},
            },
        ],
        limit=10,
    )

    topics = {candidate.topic.casefold(): candidate for candidate in candidates}
    assert "obsidian" in topics
    assert "markdown" in topics
    assert topics["markdown"].document_ids == ("doc-1", "doc-2")
    assert topics["markdown"].confidence > 0.5
    assert candidates[0].score == 1.0


def test_extract_interest_candidates_is_deterministic_and_validates_limit() -> None:
    """같은 문서는 같은 후보 순서를 만들고 잘못된 limit을 거절하는지 검증한다."""
    import pytest

    documents = [
        {
            "document_id": "doc-1",
            "title": "PostgreSQL",
            "summary": "데이터베이스와 pgvector",
            "domain": "product",
            "source_metadata": {},
        }
    ]

    assert extract_interest_candidates(documents) == extract_interest_candidates(documents)
    with pytest.raises(ValueError, match="limit"):
        extract_interest_candidates(documents, limit=0)
