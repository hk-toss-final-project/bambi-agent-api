"""근거 문서에서 주제에 해당하는 문장만 남기는 기능.

수집된 기사는 한 편에 여러 사안을 싣는다. 그 문서를 통째로 생성 프롬프트에
넣으면 리포트가 주제 밖 사실까지 옮겨 적는다(2026-08-11 실측: '폭염' 섹션이
같은 기사에 실린 KIA의 점수·연승·투수 성적을 그대로 썼다).

**프롬프트 규칙으로는 못 막았다.** 생성 프롬프트 규칙 5에 "쓴다/쓰지 않는다"를
예시까지 적어 넣고 벤치마크로 쟀는데 그대로 유출됐다. 그래서 생성에 넣기 전에
근거 자체를 좁힌다.

**임베딩 유사도로도 못 가른다.** 문장별 유사도를 실측하니 남겨야 할 문장
("대구 낮 기온은 38도였다" 0.124)이 버려야 할 문장("KIA 선발 투수는 7이닝
무실점" 0.159)보다 낮았다. 짧은 문장만 떼어 재면 앞뒤 문맥이 사라져서, '폭염'
이라는 말이 없는 폭염 문장이 밀려난다. 그래서 문맥을 읽는 LLM으로 판단한다.

**새 문장을 만들지 못하게 한다.** 골라낸 문장이 원문에 그대로 있는지 대조하고,
없으면 버린다. 근거를 다듬다가 근거를 지어내면 고치려던 문제보다 나쁘다.
"""

from __future__ import annotations

import json
import logging
from collections.abc import Sequence
from dataclasses import replace
from pathlib import Path

from agent.llm.api import complete, strip_json_fence
from shared.report_models import ReportContextDocument

logger = logging.getLogger("agent.report_builder.topic_focus")

_PROMPT_PATH = (
    Path(__file__).parents[2] / "prompts" / "templates" / "topic_evidence_focus.md"
)
_SYSTEM_PROMPT = _PROMPT_PATH.read_text(encoding="utf-8").strip()


def _normalize(text: str) -> str:
    """원문 대조용으로 공백 차이를 지운다."""
    return "".join(text.split())


def _build_user_prompt(topic: str, documents: Sequence[ReportContextDocument]) -> str:
    """주제와 근거 문서를 편집자에게 넘길 프롬프트로 조립한다."""
    blocks = [f"주제: {topic}", "", "문서:"]
    for document in documents:
        blocks.append(f"[{document.reference}] {document.title}")
        blocks.append(document.content.strip())
        blocks.append("")
    return "\n".join(blocks)


def _kept_sentences(payload: object) -> dict[str, tuple[bool, list[str]]]:
    """편집자 응답을 reference별 (주제 관련 여부, 문장 목록)으로 정규화한다."""
    if not isinstance(payload, dict):
        raise ValueError("근거 선별 응답은 JSON 객체여야 합니다.")
    kept: dict[str, tuple[bool, list[str]]] = {}
    for item in payload.get("documents") or []:
        if not isinstance(item, dict):
            continue
        reference = str(item.get("reference") or "").strip()
        if not reference:
            continue
        sentences = [
            str(sentence).strip()
            for sentence in (item.get("sentences") or [])
            if str(sentence).strip()
        ]
        # relevant를 안 보내면 문장이 하나라도 있는 것을 관련 있다는 뜻으로 본다.
        relevant = bool(item.get("relevant", bool(sentences)))
        kept[reference] = (relevant, sentences)
    return kept


def focus_documents_on_topic(
    topic: str,
    documents: Sequence[ReportContextDocument],
    *,
    model: str = "gpt-4.1-mini",
) -> list[ReportContextDocument]:
    """근거 문서 본문을 주제에 해당하는 문장만 남기도록 좁힌다.

    주제 하나당 LLM을 한 번 부른다. 문서마다 부르면 리포트당 호출이 열 번대로
    늘어난다.

    **실패하면 원본을 그대로 돌려준다.** 선별에 실패했다고 근거를 통째로 잃으면
    섹션이 사라진다. 초점이 흐려지는 것보다 나쁜 결과다.

    반대로 **성공했는데 남은 문장이 없는 문서는 버린다.** 편집자가 "이 문서에는
    주제 얘기가 없다"고 판단한 것이므로, 그대로 두면 무관한 근거를 인용해 섹션을
    채우게 된다.

    Args:
        topic: 이 근거들이 뒷받침할 소주제
        documents: 좁힐 근거 문서 목록
        model: 선별에 쓸 OpenAI 모델

    Returns:
        본문이 좁혀진 문서 목록. 주제와 무관한 문서는 빠진다
    """
    # 본문·참조가 없는 형태(테스트 더미 등)는 좁히지 않고 통과시킨다
    # — select_personal_documents와 같은 관용 규칙이다.
    candidates = [
        document
        for document in documents
        if str(getattr(document, "content", "") or "").strip()
        and str(getattr(document, "reference", "") or "").strip()
    ]
    if not topic.strip() or not candidates:
        return list(documents)
    passthrough = [document for document in documents if document not in candidates]

    try:
        raw = complete(_SYSTEM_PROMPT, _build_user_prompt(topic, candidates), model=model)
        kept = _kept_sentences(json.loads(strip_json_fence(raw)))
    except Exception as error:  # noqa: BLE001 — 선별 실패가 근거를 없애면 안 된다
        logger.warning("근거 선별 실패, 원본을 그대로 쓴다 (topic=%s): %s", topic, error)
        return list(documents)

    focused: list[ReportContextDocument] = [*passthrough]
    for document in candidates:
        if document.reference not in kept:
            # 편집자가 빠뜨린 문서다. 판단을 못 받았으니 원본을 유지한다.
            focused.append(document)
            continue
        relevant, requested = kept[document.reference]
        if not relevant:
            logger.info(
                "주제와 무관한 근거를 제외한다: topic=%s reference=%s",
                topic,
                document.reference,
            )
            continue
        source = _normalize(document.content)
        # 원문에 없는 문장은 버린다. 근거를 다듬다가 지어내면 안 된다.
        sentences = [
            sentence for sentence in requested if _normalize(sentence) in source
        ]
        dropped = len(requested) - len(sentences)
        if dropped:
            logger.warning(
                "원문에 없는 문장을 버렸다: topic=%s reference=%s %d건",
                topic,
                document.reference,
                dropped,
            )
        # 주제를 다루는 문서인데 남길 문장을 못 고른 경우다. 문장 선별이 과하게
        # 잘라낸 쪽에 가까우므로 원본을 유지한다 — 근거를 잃는 것이 초점이
        # 흐려지는 것보다 나쁘다(2026-08-11 실측: '프로야구' 근거 "리그 선두 구단이
        # 5연승"이 통째로 사라져 섹션이 빠졌다).
        focused.append(
            replace(document, content=" ".join(sentences)) if sentences else document
        )
    return focused
