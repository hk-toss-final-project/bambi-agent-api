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


def test_parse_report_generation_accepts_live_source_reference() -> None:
    """실시간 자료 참조(L1)를 본문 인용과 명시 Citation 양쪽에서 인식한다.

    live_sources가 L{n} 참조를 쓰므로, 본문 정규식이 L 접두사를 놓치면
    실시간 근거 인용이 Citation 목록에서 누락된다.
    """
    result = parse_report_generation(
        '{"title":"제목","summary":"요약",'
        '"body":"기존 맥락. [P1] 오늘 소식이다. [L1]","citation_refs":["L2"]}',
        allowed_references=["P1", "L1", "L2"],
    )

    assert result.citation_references == ("L2", "P1", "L1")


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


def _good_json(body: str) -> str:
    """품질 검사를 통과하는 생성 응답 JSON을 만든다."""
    import json

    return json.dumps({"title": "제목", "summary": "요약", "body": body, "citation_refs": ["P1"]})


def _long_cited_body() -> str:
    """근거를 인용하고 충분히 긴 본문(품질 통과용)."""
    return "PostgreSQL 버전 관리 분석[P1]. " + "상세한 설명 문장입니다. " * 40


def test_quality_retry_regenerates_when_first_is_too_short(monkeypatch: pytest.MonkeyPatch) -> None:
    """1차 결과가 품질 미달이면 교정 지시를 붙여 재생성한다."""
    calls: list[str] = []

    def _complete(system_prompt: str, user_prompt: str, model: str) -> str:
        calls.append(user_prompt)
        if len(calls) == 1:
            return _good_json("짧음[P1].")          # 1차: 너무 짧음 → 재생성
        return _good_json(_long_cited_body())        # 2차: 통과

    monkeypatch.setattr(generation, "complete", _complete)

    result = generation.generate_report_content_with_quality(
        topic="주제", content_type="card", language="ko", contexts=[_context()], model="m"
    )

    assert len(calls) == 2                            # 재생성 1회 발생
    assert "[재생성 지시]" in calls[1]                # 2차 프롬프트에 교정 지시가 들어감
    assert result.body.startswith("PostgreSQL")       # 2차(통과) 결과를 반환


def test_quality_retry_stops_after_one_regeneration(monkeypatch: pytest.MonkeyPatch) -> None:
    """상한(1회)까지 재생성해도 미달이면 마지막 결과를 그대로 반환한다."""
    calls: list[str] = []

    def _complete(system_prompt: str, user_prompt: str, model: str) -> str:
        calls.append(user_prompt)
        return _good_json("계속 짧음[P1].")           # 매번 품질 미달

    monkeypatch.setattr(generation, "complete", _complete)

    result = generation.generate_report_content_with_quality(
        topic="주제", content_type="card", language="ko", contexts=[_context()], model="m"
    )

    assert len(calls) == 2                            # 1차 + 재생성 1회로 멈춤 (무한 아님)
    assert result is not None                         # 미달이어도 결과는 반환


def test_quality_no_retry_when_first_passes(monkeypatch: pytest.MonkeyPatch) -> None:
    """1차가 품질을 통과하면 재생성하지 않는다 (불필요한 비용 방지)."""
    calls: list[str] = []

    def _complete(system_prompt: str, user_prompt: str, model: str) -> str:
        calls.append(user_prompt)
        return _good_json(_long_cited_body())

    monkeypatch.setattr(generation, "complete", _complete)

    generation.generate_report_content_with_quality(
        topic="주제", content_type="card", language="ko", contexts=[_context()], model="m"
    )

    assert len(calls) == 1                            # 재생성 없음


def test_quality_retry_recovers_from_malformed_json(monkeypatch: pytest.MonkeyPatch) -> None:
    """1차 응답이 깨진 JSON이면 Job 전체 실패 대신 한 번 재생성한다."""
    calls: list[str] = []

    def _complete(system_prompt: str, user_prompt: str, model: str) -> str:
        calls.append(user_prompt)
        if len(calls) == 1:
            return "죄송합니다, JSON이 아닌 응답"      # 1차: 파싱 실패
        return _good_json(_long_cited_body())         # 2차: 정상

    monkeypatch.setattr(generation, "complete", _complete)

    result = generation.generate_report_content_with_quality(
        topic="주제", content_type="card", language="ko", contexts=[_context()], model="m"
    )

    assert len(calls) == 2
    assert result.body.startswith("PostgreSQL")


def test_quality_retry_reraises_if_regeneration_also_malformed(monkeypatch: pytest.MonkeyPatch) -> None:
    """재생성도 깨진 JSON이면 예외를 그대로 올린다 (조용히 삼키지 않는다)."""

    def _complete(system_prompt: str, user_prompt: str, model: str) -> str:
        return "계속 JSON 아님"

    monkeypatch.setattr(generation, "complete", _complete)

    with pytest.raises(ValueError):
        generation.generate_report_content_with_quality(
            topic="주제", content_type="card", language="ko", contexts=[_context()], model="m"
        )
