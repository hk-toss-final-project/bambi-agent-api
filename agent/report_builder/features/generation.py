"""Report Builder 제목·요약·본문 생성과 LLM 응답 검증 기능.

개인 Wiki와 Global 최신 문서에 안정적인 참조 ID를 붙여 LLM에 전달하고,
허용된 참조만 Citation 후보로 반환하는 실제 생성 경계를 제공한다.
"""

import json
import re
from collections.abc import Sequence
from pathlib import Path

from agent.llm.api import complete, strip_json_fence

# 하위 호환 재노출: 기존 generation.ReportContextDocument 등 사용처를 유지한다.
from shared.report_models import ReportContextDocument, GeneratedReportContent
from shared.contracts import FeatureRequest, FeatureResult
from shared.feature_runtime import execute_feature_implementation

_PROMPT_PATH = Path(__file__).parents[2] / "prompts" / "templates" / "report_builder_system.md"
_SYSTEM_PROMPT = _PROMPT_PATH.read_text(encoding="utf-8").strip()
# P=개인 Wiki, G=Global 문서, L=실시간 외부 자료(live_sources). 세 접두사가
# 실제 근거 참조 체계의 전부이며, 프롬프트의 인용 지시와 함께 유지해야 한다.
_CITATION_REF = re.compile(r"\[([PGL]\d+)\]")
_MAX_CONTEXT_CHARS = 16000


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
    )


def generate_report_content(
    *,
    topic: str,
    content_type: str,
    language: str,
    contexts: Sequence[ReportContextDocument],
    model: str = "gpt-4.1-mini",
) -> GeneratedReportContent:
    """개인 Wiki와 최신 Global 근거로 Report Builder 콘텐츠 JSON을 생성한다."""
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
    user_prompt = (
        f"주제: {topic}\n"
        f"콘텐츠 유형: {content_type}\n"
        f"언어: {language}\n\n"
        "아래 근거만 사용해 콘텐츠를 생성하세요.\n\n"
        + "\n\n---\n\n".join(context_blocks)
    )
    raw = complete(_SYSTEM_PROMPT, user_prompt, model=model)
    return parse_report_generation(
        raw,
        allowed_references=included_references,
    )


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


async def report_010(request: FeatureRequest) -> FeatureResult:
    """[REPORT-010] 콘텐츠 태그 생성.

    콘텐츠 검색과 추천에 사용할 태그를 생성한다.
    """
    raise NotImplementedError("[REPORT-010] 기능 구현이 필요합니다.")
