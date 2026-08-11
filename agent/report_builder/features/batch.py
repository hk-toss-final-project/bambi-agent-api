"""비긴급 Report 초안을 OpenAI Batch로 등록하고 완료 결과를 저장하는 경계."""

from __future__ import annotations

from asyncio import to_thread
from collections.abc import Mapping, Sequence
from dataclasses import asdict
from datetime import UTC, datetime
from hashlib import sha256

from psycopg import AsyncConnection

from agent.report_builder.features import quality
from agent.report_builder.features.generation import (
    build_report_generation_prompt,
    generate_report_content_with_quality,
    parse_report_generation,
)
from infrastructure.persistence.api import (
    ClaimedBatchResultItem,
    EnqueueLlmBatchItemCommand,
    StoredLlmBatchItem,
    complete_waiting_provider_job,
    enqueue_llm_batch_item,
    persist_report_generation,
    set_personal_wiki_scope,
)
from shared.report_models import ReportContextDocument

type DictRow = dict[str, object]


def report_context_from_mapping(value: Mapping[str, object]) -> ReportContextDocument:
    """고정된 Job·Batch Context 객체를 ReportContextDocument로 검증 변환한다."""
    required = {
        "reference",
        "document_version_id",
        "chunk_id",
        "namespace_key",
        "title",
        "content",
    }
    missing = sorted(required - value.keys())
    if missing:
        raise ValueError(f"Report Batch Context 필드가 없습니다: {', '.join(missing)}")
    return ReportContextDocument(
        reference=str(value["reference"]),
        document_version_id=str(value["document_version_id"]),
        chunk_id=str(value["chunk_id"]),
        namespace_key=str(value["namespace_key"]),
        title=str(value["title"]),
        content=str(value["content"]),
        url=str(value["url"]) if value.get("url") else None,
        score=float(value.get("score") or 0.0),
        context_role=str(value.get("context_role") or "retrieved"),
        source_updated_at=(
            str(value["source_updated_at"])
            if value.get("source_updated_at")
            else None
        ),
        image_url=str(value["image_url"]) if value.get("image_url") else None,
    )


def _report_batch_custom_id(job_id: str, system_prompt: str, user_prompt: str) -> str:
    """Job과 고정 Prompt로 멱등 Report Batch custom_id를 만든다."""
    digest = sha256(
        f"{job_id}\n{system_prompt}\n{user_prompt}".encode("utf-8")
    ).hexdigest()
    return f"report-generation:{digest}"


async def stage_report_generation_batch(
    connection: AsyncConnection[DictRow],
    *,
    user_id: str,
    job_id: str,
    attempt_number: int,
    topic: str,
    content_type: str,
    language: str,
    contexts: Sequence[ReportContextDocument],
    model: str,
    topics: Sequence[str] = (),
    interest_bundle: Mapping[str, object] | None = None,
) -> StoredLlmBatchItem:
    """검색이 끝나 고정된 Report Context와 Prompt를 Chat Completion Batch로 등록한다."""
    prompt = build_report_generation_prompt(
        topic=topic,
        content_type=content_type,
        language=language,
        contexts=contexts,
        model=model,
        topics=topics,
        interest_bundle=interest_bundle,
    )
    return await enqueue_llm_batch_item(
        connection,
        EnqueueLlmBatchItemCommand(
            user_id=user_id,
            job_id=job_id,
            custom_id=_report_batch_custom_id(
                job_id,
                prompt.system_prompt,
                prompt.user_prompt,
            ),
            endpoint="/v1/chat/completions",
            model_name=model,
            workload="report_generation",
            resource_type="generation_request",
            resource_id=job_id,
            request_body={
                "model": model,
                "messages": [
                    {"role": "system", "content": prompt.system_prompt},
                    {"role": "user", "content": prompt.user_prompt},
                ],
                "temperature": 0.3,
            },
            context={
                "topic": topic,
                "topics": list(topics),
                "content_type": content_type,
                "language": language,
                "interest_bundle": dict(interest_bundle or {}),
                "allowed_references": list(prompt.allowed_references),
                "contexts": [asdict(context) for context in contexts],
                "attempt_number": attempt_number,
                "staged_at": datetime.now(UTC).isoformat(),
            },
        ),
    )


def _chat_completion_text(result_body: Mapping[str, object]) -> str:
    """OpenAI Chat Completion Batch 응답 Body에서 첫 Assistant Text를 추출한다."""
    choices = result_body.get("choices")
    if not isinstance(choices, list) or not choices:
        raise ValueError("Report Batch 결과에 choices가 없습니다.")
    choice = choices[0]
    message = choice.get("message") if isinstance(choice, Mapping) else None
    content = message.get("content") if isinstance(message, Mapping) else None
    if not isinstance(content, str) or not content.strip():
        raise ValueError("Report Batch 결과에 Assistant 본문이 없습니다.")
    return content


def _batch_latency_ms(context: Mapping[str, object]) -> int:
    """Item 등록부터 도메인 반영까지 경과 시간을 millisecond로 계산한다."""
    try:
        staged_at = datetime.fromisoformat(str(context.get("staged_at") or ""))
    except ValueError:
        return 0
    if staged_at.tzinfo is None:
        staged_at = staged_at.replace(tzinfo=UTC)
    return max(0, int((datetime.now(UTC) - staged_at).total_seconds() * 1000))


async def apply_report_generation_batch_result(
    connection: AsyncConnection[DictRow],
    item: ClaimedBatchResultItem,
) -> dict[str, object]:
    """Batch 초안을 검증·필요 시 한 번 교정하고 기존 생성 저장 경계로 완료한다."""
    if item.workload != "report_generation" or item.job_id is None:
        raise ValueError("Report Batch 결과에 workload 또는 job_id가 없습니다.")
    raw_contexts = item.context.get("contexts")
    if not isinstance(raw_contexts, list):
        raise ValueError("Report Batch 결과에 고정 Context가 없습니다.")
    contexts = [
        report_context_from_mapping(value)
        for value in raw_contexts
        if isinstance(value, Mapping)
    ]
    if len(contexts) != len(raw_contexts):
        raise ValueError("Report Batch Context 중 객체가 아닌 값이 있습니다.")
    allowed = item.context.get("allowed_references")
    if not isinstance(allowed, list):
        raise ValueError("Report Batch 허용 Citation Snapshot이 없습니다.")
    generated = parse_report_generation(
        _chat_completion_text(item.result_body),
        allowed_references=[str(value) for value in allowed],
    )
    verdict = quality.evaluate_report(generated, context_count=len(contexts))
    if verdict.should_regenerate:
        generated = await to_thread(
            generate_report_content_with_quality,
            topic=str(item.context.get("topic") or ""),
            topics=[str(value) for value in item.context.get("topics") or []],
            content_type=str(item.context.get("content_type") or ""),
            language=str(item.context.get("language") or "ko"),
            contexts=contexts,
            model=item.model_name,
            correction=verdict.correction,
            interest_bundle=(
                item.context.get("interest_bundle")
                if isinstance(item.context.get("interest_bundle"), Mapping)
                else None
            ),
            max_regenerations=1,
        )
    await set_personal_wiki_scope(connection, user_id=item.user_id)
    result = await persist_report_generation(
        connection,
        job_id=item.job_id,
        user_id=item.user_id,
        attempt_number=int(item.context.get("attempt_number") or 1),
        content_type=str(item.context.get("content_type") or ""),
        generated=generated,
        contexts=contexts,
        latency_ms=_batch_latency_ms(item.context),
        review_outcome="batch_rule_quality",
        review_problem=verdict.reason if verdict.should_regenerate else "",
    )
    await complete_waiting_provider_job(
        connection,
        job_id=item.job_id,
        user_id=item.user_id,
        result=result,
    )
    return result
