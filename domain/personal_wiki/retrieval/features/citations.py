"""Bambi 생성 결과와 개인 Wiki Citation 연결 기능 구현."""

from collections.abc import Sequence
from typing import Any

from psycopg import AsyncConnection

from infrastructure.persistence.features.generation_runtime import (
    persist_bambi_generation,
)
from shared.bambi_models import BambiContextDocument, GeneratedBambiContent


# MVP: agent-api-mvp-scope.md에서 구현 대상으로 지정된 기능입니다.
async def prag_007(
    connection: AsyncConnection[dict[str, Any]],
    *,
    job_id: str,
    user_id: str,
    attempt_number: int,
    content_type: str,
    generated: GeneratedBambiContent,
    contexts: Sequence[BambiContextDocument],
    latency_ms: int,
) -> dict[str, object]:
    """[PRAG-007] Citation 연결.

    생성 결과와 참조한 개인 Wiki 문서를 연결한다.
    """
    available = {context.reference for context in contexts}
    missing = sorted(set(generated.citation_references) - available)
    if missing:
        raise ValueError(
            "PRAG-007이 연결할 수 없는 Citation 참조입니다: " + ", ".join(missing)
        )
    return await persist_bambi_generation(
        connection,
        job_id=job_id,
        user_id=user_id,
        attempt_number=attempt_number,
        content_type=content_type,
        generated=generated,
        contexts=contexts,
        latency_ms=latency_ms,
    )
