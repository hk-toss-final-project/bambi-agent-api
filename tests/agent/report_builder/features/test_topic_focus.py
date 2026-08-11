"""근거를 소주제에 해당하는 문장만 남기도록 좁히는 규칙을 검증한다.

근거를 다듬다가 근거를 지어내면 고치려던 문제보다 나쁘므로, 원문 대조와 실패
시 폴백을 중점적으로 확인한다. LLM은 실제로 부르지 않고 대체한다.
"""

import pytest

from agent.report_builder.features import topic_focus
from agent.report_builder.features.topic_focus import focus_documents_on_topic
from shared.report_models import ReportContextDocument

_ARTICLE = (
    "폭염 특보로 어제 경기가 취소됐다가 기온이 내려가 오늘 재개됐다. "
    "대구 낮 기온은 38도였다. "
    "한편 재개된 경기에서 KIA는 삼성을 7-3으로 꺾고 3연승을 달렸다."
)


def _document(reference: str = "G1", content: str = _ARTICLE) -> ReportContextDocument:
    """근거 문서 한 건을 만든다."""
    return ReportContextDocument(
        reference=reference,
        document_version_id=f"version-{reference}",
        chunk_id=f"chunk-{reference}",
        namespace_key="global",
        title="폭염으로 프로야구 경기 취소 후 재개",
        content=content,
        url="https://example.test/article",
        score=0.9,
    )


def _answer(monkeypatch: pytest.MonkeyPatch, payload: str) -> list[str]:
    """편집자 응답을 고정하고 전달된 프롬프트를 기록한다."""
    prompts: list[str] = []

    def _fake(_system: str, user: str, **_kwargs: object) -> str:
        prompts.append(user)
        return payload

    monkeypatch.setattr(topic_focus, "complete", _fake)
    return prompts


def test_keeps_only_the_sentences_about_the_topic(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """주제에 해당하는 문장만 남기고 나머지는 버린다.

    2026-08-11 실측: 같은 기사에 실렸다는 이유로 KIA의 점수·연승이 '폭염' 섹션에
    그대로 옮겨졌다.
    """
    _answer(
        monkeypatch,
        '{"documents": [{"reference": "G1", "sentences": ['
        '"폭염 특보로 어제 경기가 취소됐다가 기온이 내려가 오늘 재개됐다.", '
        '"대구 낮 기온은 38도였다."]}]}',
    )

    focused = focus_documents_on_topic("폭염", [_document()])

    assert len(focused) == 1
    assert "38도" in focused[0].content
    assert "7-3" not in focused[0].content
    assert "3연승" not in focused[0].content


def test_drops_sentences_that_are_not_in_the_source(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """원문에 없는 문장은 버린다.

    근거를 좁히다가 새 문장을 만들면 그 문장이 곧 근거가 된다. 인용까지 붙으므로
    지어낸 사실이 출처를 가진 것처럼 보인다.
    """
    _answer(
        monkeypatch,
        '{"documents": [{"reference": "G1", "sentences": ['
        '"대구 낮 기온은 38도였다.", '
        '"기상청은 내일 40도를 예보했다."]}]}',
    )

    focused = focus_documents_on_topic("폭염", [_document()])

    assert focused[0].content == "대구 낮 기온은 38도였다."


def test_drops_documents_without_any_topic_sentence(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """주제 문장이 하나도 없는 문서는 근거에서 뺀다.

    그대로 두면 무관한 근거를 인용해 섹션을 채운다(2026-08-11 실측: '김건희'
    섹션이 서학개미 증시 기사를 인용했다).
    """
    _answer(monkeypatch, '{"documents": [{"reference": "G1", "relevant": false, "sentences": []}]}')

    assert focus_documents_on_topic("김건희", [_document()]) == []


def test_keeps_the_original_when_the_document_is_relevant_but_no_sentence_is_picked(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """주제를 다루는 문서인데 문장을 못 고르면 원본을 유지한다.

    문서 판단과 문장 선별을 나눈 이유가 이것이다. 둘을 묶어 두면 표현이 다른
    문장을 못 골라내는 순간 근거가 통째로 사라진다(2026-08-11 실측: '프로야구'
    근거 "리그 선두 구단이 5연승"이 사라져 섹션이 빠졌다).
    """
    _answer(monkeypatch, '{"documents": [{"reference": "G1", "relevant": true, "sentences": []}]}')

    focused = focus_documents_on_topic("폭염", [_document()])

    assert focused[0].content == _ARTICLE


def test_keeps_the_original_when_the_model_fails(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """호출이 실패하면 원본을 그대로 쓴다.

    선별 실패로 근거를 통째로 잃으면 섹션이 사라진다. 초점이 흐려지는 것보다 나쁘다.
    """

    def _boom(*_args: object, **_kwargs: object) -> str:
        raise RuntimeError("모델 호출 실패")

    monkeypatch.setattr(topic_focus, "complete", _boom)

    documents = [_document()]

    assert focus_documents_on_topic("폭염", documents) == documents


def test_keeps_the_original_when_the_response_is_broken(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """깨진 응답도 원본 유지로 흘려보낸다."""
    _answer(monkeypatch, "이건 JSON이 아니다")

    documents = [_document()]

    assert focus_documents_on_topic("폭염", documents) == documents


def test_keeps_documents_the_model_did_not_judge(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """편집자가 빠뜨린 문서는 원본을 유지한다.

    판단을 못 받은 것과 "주제 얘기가 없다"고 판단된 것은 다르다.
    """
    _answer(monkeypatch, '{"documents": [{"reference": "G1", "relevant": false, "sentences": []}]}')

    focused = focus_documents_on_topic("폭염", [_document(), _document("G2")])

    assert [document.reference for document in focused] == ["G2"]


def test_skips_the_call_without_documents(monkeypatch: pytest.MonkeyPatch) -> None:
    """근거가 없으면 호출하지 않는다."""

    def _unexpected(*_args: object, **_kwargs: object) -> str:
        raise AssertionError("근거가 없으면 모델을 부르면 안 된다")

    monkeypatch.setattr(topic_focus, "complete", _unexpected)

    assert focus_documents_on_topic("폭염", []) == []


def test_prompt_carries_the_topic_and_document_bodies(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """주제와 문서 본문을 프롬프트에 함께 넣는다."""
    prompts = _answer(
        monkeypatch,
        '{"documents": [{"reference": "G1", "relevant": true, "sentences": ["대구 낮 기온은 38도였다."]}]}',
    )

    focus_documents_on_topic("폭염", [_document()])

    assert "주제: 폭염" in prompts[0]
    assert "[G1]" in prompts[0]
    assert "KIA는 삼성을 7-3으로" in prompts[0]
