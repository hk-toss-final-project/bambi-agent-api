"""Report Builder 제목·요약·본문 생성과 LLM 응답 검증 기능.

개인 Wiki와 Global 최신 문서에 안정적인 참조 ID를 붙여 LLM에 전달하고,
허용된 참조만 Citation 후보로 반환하는 실제 생성 경계를 제공한다.
"""

import json
import logging
import re
from collections.abc import Sequence
from pathlib import Path

from agent.llm.api import complete, strip_json_fence
from agent.report_builder.features import quality

# 하위 호환 재노출: 기존 generation.ReportContextDocument 등 사용처를 유지한다.
from shared.report_models import ReportContextDocument, GeneratedReportContent
from shared.contracts import FeatureRequest, FeatureResult
from shared.feature_runtime import execute_feature_implementation

logger = logging.getLogger("agent.report_builder.generation")

_PROMPT_PATH = Path(__file__).parents[2] / "prompts" / "templates" / "report_builder_system.md"
_SYSTEM_PROMPT = _PROMPT_PATH.read_text(encoding="utf-8").strip()
# P=개인 Wiki, G=Global 문서, L=실시간 외부 자료(live_sources). 세 접두사가
# 실제 근거 참조 체계의 전부이며, 프롬프트의 인용 지시와 함께 유지해야 한다.
_CITATION_REF = re.compile(r"\[([PGL]\d+)\]")
_MAX_CONTEXT_CHARS = 16000


# [REPORT-010] 콘텐츠 태그 제약. 검색·추천 UI가 카드에 노출하므로 개수와 길이를
# 코드가 강제한다 — 프롬프트로만 부탁하면 모델이 10개를 주거나 문장을 넣는다.
_MAX_CONTENT_TAGS = 5
_MAX_CONTENT_TAG_CHARS = 20


# MVP: agent-api-mvp-scope.md에서 구현 대상으로 지정된 기능입니다.
def normalize_content_tags(raw_tags: object) -> tuple[str, ...]:
    """[REPORT-010] 생성 응답의 태그를 검증·정리해 반환한다.

    **실패하지 않는다.** 태그는 검색·추천을 돕는 보조 정보라, 형식이 잘못됐다고
    리포트 생성 전체를 버릴 이유가 없다. 쓸 수 없는 값은 조용히 걸러낸다.

    정리 규칙:
    - 문자열이 아니거나 빈 값은 버린다.
    - 앞뒤 공백을 정리하고 연속 공백을 하나로 줄인다.
    - 20자를 넘으면 버린다(자르면 뜻이 깨진 태그가 남는다).
    - 대소문자·공백을 무시하고 중복을 제거한다. 먼저 온 표기를 남긴다.
    - 최대 5개까지만 취한다.

    Args:
        raw_tags: LLM 응답의 `tags` 값. 목록이 아니면 빈 튜플을 반환한다.

    Returns:
        정리된 태그 튜플. 쓸 수 있는 태그가 없으면 빈 튜플.
    """
    if not isinstance(raw_tags, list):
        return ()
    selected: list[str] = []
    seen: set[str] = set()
    for item in raw_tags:
        if not isinstance(item, str):
            continue
        tag = " ".join(item.split())
        if not tag or len(tag) > _MAX_CONTENT_TAG_CHARS:
            continue
        key = tag.casefold()
        if key in seen:
            continue
        seen.add(key)
        selected.append(tag)
        if len(selected) >= _MAX_CONTENT_TAGS:
            break
    return tuple(selected)


def parse_report_generation(
    raw_response: str,
    *,
    allowed_references: Sequence[str],
) -> GeneratedReportContent:
    """LLM JSON을 파싱하고 존재하지 않는 Citation 참조를 차단한다."""
    try:
        payload = json.loads(strip_json_fence(raw_response))
    except json.JSONDecodeError as error:
        raise ValueError(f"Report Builder 생성 응답이 JSON 형식이 아닙니다: {error}") from error
    if not isinstance(payload, dict):
        raise ValueError("Report Builder 생성 응답은 JSON 객체여야 합니다.")
    title = str(payload.get("title") or "").strip()
    summary = str(payload.get("summary") or "").strip()
    body = str(payload.get("body") or "").strip()
    if not title or not summary or not body:
        raise ValueError("Report Builder 생성 응답에 title, summary, body가 모두 필요합니다.")
    allowed = set(allowed_references)
    response_refs = payload.get("citation_refs") or []
    requested = [str(item).strip() for item in response_refs if str(item).strip()]
    requested.extend(_CITATION_REF.findall(body))
    invalid = sorted({reference for reference in requested if reference not in allowed})
    if invalid:
        raise ValueError(f"허용되지 않은 Citation 참조입니다: {', '.join(invalid)}")
    citations: list[str] = []
    for reference in requested:
        if reference in allowed and reference not in citations:
            citations.append(reference)
    return GeneratedReportContent(
        title=title,
        summary=summary,
        body=body,
        citation_references=tuple(citations),
        content_tags=normalize_content_tags(payload.get("tags")),
    )


def generate_report_content(
    *,
    topic: str,
    content_type: str,
    language: str,
    contexts: Sequence[ReportContextDocument],
    model: str = "gpt-4.1-mini",
    correction: str = "",
    topics: Sequence[str] = (),
) -> GeneratedReportContent:
    """개인 Wiki와 최신 Global 근거로 Report Builder 콘텐츠 JSON을 생성한다.

    correction이 주어지면(품질 재생성 시) 이전 생성의 문제를 교정하는 지시를
    프롬프트 앞부분에 넣는다. 같은 근거·프롬프트로 다시 생성하면 결과가 같으므로,
    무엇이 문제였는지 알려줘야 재생성이 실제로 나아진다.
    """
    if not contexts:
        raise ValueError("Report Builder 콘텐츠 생성에 사용할 검색 Context가 없습니다.")
    context_blocks: list[str] = []
    current_size = 0
    included_references: list[str] = []
    for context in contexts:
        block = (
            f"[{context.reference}] {context.title}\n"
            f"URL: {context.url or '(개인 Wiki)'}\n"
            f"내용:\n{context.content.strip()}"
        )
        if context_blocks and current_size + len(block) > _MAX_CONTEXT_CHARS:
            break
        context_blocks.append(block)
        included_references.append(context.reference)
        current_size += len(block)
    correction_block = f"[재생성 지시] {correction}\n\n" if correction else ""
    # 주제가 여럿이면(아침 요약) 주제마다 섹션을 두게 한다. 근거는 이미 주제별로
    # 몫을 나눠 담겨 있지만, 지시가 없으면 LLM이 한 주제로 몰아 쓰고 나머지를 흘린다.
    covered = [str(item).strip() for item in topics if str(item).strip()]
    if len(covered) > 1:
        topic_block = f"주제: {topic}\n" + "다룰 소주제(각각 별도 섹션으로, 순서대로 빠짐없이):\n" + "".join(
            f"  - {item}\n" for item in covered
        )
    else:
        topic_block = f"주제: {topic}\n"
    user_prompt = (
        topic_block
        + f"콘텐츠 유형: {content_type}\n"
        f"언어: {language}\n\n"
        + correction_block
        + "아래 근거만 사용해 콘텐츠를 생성하세요.\n\n"
        + "\n\n---\n\n".join(context_blocks)
    )
    raw = complete(_SYSTEM_PROMPT, user_prompt, model=model)
    return parse_report_generation(
        raw,
        allowed_references=included_references,
    )


def generate_report_content_with_quality(
    *,
    topic: str,
    content_type: str,
    language: str,
    contexts: Sequence[ReportContextDocument],
    model: str = "gpt-4.1-mini",
    max_regenerations: int = 1,
    correction: str = "",
    topics: Sequence[str] = (),
) -> GeneratedReportContent:
    """콘텐츠를 생성하고 무료 품질 검사를 거쳐, 필요하면 한 번 재생성한다.

    생성 → 품질 판정(quality.evaluate_report) → 재생성 대상이면 교정 지시를 붙여
    다시 생성하는 루프다. LLM이 깨진 JSON을 뱉어 파싱이 실패한 경우도 "가장 심한
    품질 실패"로 보고 같은 방식으로 한 번 재생성한다(이전에는 Job 전체가 실패해
    검색까지 다시 했다).

    재생성 상한(max_regenerations)을 두어 무한 루프와 비용 폭주를 막는다. 상한까지
    가도 여전히 품질 미달이면 마지막 결과를 그대로 반환한다(완벽하지 못하면 있는 것으로).

    Args:
        topic·content_type·language·contexts·model: generate_report_content와 동일
        max_regenerations: 재생성 최대 횟수 (기본 1회)
        correction: 첫 생성부터 반영할 교정 지시. 검토자(critic)가 재작성을
            요구해 다시 들어올 때 그 지적을 넘겨받는 통로다.

    Returns:
        (가능하면 품질을 통과한) 생성 콘텐츠
    """
    content: GeneratedReportContent | None = None
    for attempt in range(max_regenerations + 1):
        try:
            content = generate_report_content(
                topic=topic,
                content_type=content_type,
                language=language,
                contexts=contexts,
                model=model,
                correction=correction,
                topics=topics,
            )
        except ValueError as error:
            # 응답이 깨진(파싱 실패) 경우. 상한이 남았으면 교정 지시를 붙여 재생성한다.
            if attempt >= max_regenerations:
                raise
            logger.info("생성 응답 파싱 실패, 재생성한다(%d회차): %s", attempt + 1, error)
            correction = (
                "이전 응답이 올바른 JSON 형식이 아니었습니다. title·summary·body·"
                "citation_refs 키를 가진 JSON 객체로만 응답하세요."
            )
            continue

        verdict = quality.evaluate_report(content, context_count=len(contexts))
        logger.info(
            "품질 판정(%d회차): %s — %s", attempt + 1, verdict.outcome, verdict.reason
        )
        if not verdict.should_regenerate or attempt >= max_regenerations:
            break
        correction = verdict.correction

    assert content is not None  # 루프는 최소 1회 실행되어 content를 채운다.
    return content


async def report_007(request: FeatureRequest) -> FeatureResult:
    """[REPORT-007] 콘텐츠 제목 생성.

    콘텐츠 목적에 맞는 제목을 생성한다.
    """
    raise NotImplementedError("[REPORT-007] 기능 구현이 필요합니다.")


# MVP: agent-api-mvp-scope.md에서 구현 대상으로 지정된 기능입니다.
async def report_008(request: FeatureRequest) -> FeatureResult:
    """[REPORT-008] 콘텐츠 요약 생성.

    피드와 미리보기에 사용할 요약을 생성한다.
    """
    return await execute_feature_implementation(request, feature_id="REPORT-008")


# MVP: agent-api-mvp-scope.md에서 구현 대상으로 지정된 기능입니다.
async def report_009(request: FeatureRequest) -> FeatureResult:
    """[REPORT-009] 콘텐츠 본문 생성.

    플랜과 유형에 맞는 본문을 생성한다.
    """
    return await execute_feature_implementation(request, feature_id="REPORT-009")


# MVP: agent-api-mvp-scope.md에서 구현 대상으로 지정된 기능입니다.
async def report_010(request: FeatureRequest) -> FeatureResult:
    """[REPORT-010] 콘텐츠 태그 생성.

    콘텐츠 검색과 추천에 사용할 태그를 생성한다.
    """
    return await execute_feature_implementation(request, feature_id="REPORT-010")
