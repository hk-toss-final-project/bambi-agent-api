"""개인·Global 문서 근거 기반 Report Builder 생성 응답 검증을 테스트한다."""

import pytest

from agent.report_builder.features import generation
from agent.report_builder.features.generation import (
    ReportContextDocument,
    generate_report_content,
    parse_report_generation,
)


def _context(reference: str = "P1") -> ReportContextDocument:
    """테스트용 개인 Wiki 검색 Context를 만든다."""
    return ReportContextDocument(
        reference=reference,
        document_version_id="version-1",
        chunk_id="chunk-1",
        namespace_key="user/user-1",
        title="PostgreSQL 설계",
        content="버전 테이블은 원본 변경 이력을 보존한다.",
        url=None,
        score=0.9,
    )


def test_parse_report_generation_accepts_fenced_json_and_deduplicates_refs() -> None:
    """코드 Fence JSON의 본문·명시 Citation을 검증하고 순서대로 중복 제거한다."""
    result = parse_report_generation(
        """```json
        {
          "title": "버전 관리",
          "summary": "원본 이력 관리 요약",
          "body": "버전 테이블로 변경을 추적한다. [P1] 최신 자료도 확인한다. [G1]",
          "citation_refs": ["P1", "P1"]
        }
        ```""",
        allowed_references=["P1", "G1"],
    )

    assert result.title == "버전 관리"
    assert result.citation_references == ("P1", "G1")


def test_parse_report_generation_rejects_invented_reference() -> None:
    """검색 Context에 없던 참조를 LLM이 만들면 콘텐츠 저장 전에 차단한다."""
    with pytest.raises(ValueError, match="G9"):
        parse_report_generation(
            '{"title":"제목","summary":"요약","body":"근거 [G9]"}',
            allowed_references=["P1"],
        )


def test_generate_report_content_passes_stable_context_to_llm(monkeypatch: pytest.MonkeyPatch) -> None:
    """생성기가 안정 참조와 모델을 Prompt에 전달하고 검증된 결과만 반환한다."""
    captured: dict[str, str] = {}

    def _complete(system_prompt: str, user_prompt: str, model: str) -> str:
        """실제 과금 호출 없이 전달된 Prompt를 기록한다."""
        captured.update(system=system_prompt, user=user_prompt, model=model)
        return (
            '{"title":"생성 제목","summary":"생성 요약",'
            '"body":"개인 Wiki 근거다. [P1]","citation_refs":["P1"]}'
        )

    monkeypatch.setattr(generation, "complete", _complete)

    result = generate_report_content(
        topic="데이터베이스 버전 관리",
        content_type="interest_news_card",
        language="ko",
        contexts=[_context()],
        model="test-model",
    )

    assert captured["model"] == "test-model"
    assert "[P1] PostgreSQL 설계" in captured["user"]
    assert "JSON" in captured["system"]
    assert result.citation_references == ("P1",)
