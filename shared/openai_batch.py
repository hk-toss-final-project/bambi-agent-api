"""OpenAI Batch Provider 상태를 계층 간 공유하는 불변 계약."""

from collections.abc import Mapping
from dataclasses import dataclass, field


@dataclass(frozen=True, slots=True)
class ProviderBatchSnapshot:
    """OpenAI에서 관찰한 Batch 상태와 결과 파일 식별자."""

    status: str
    input_file_id: str | None = None
    output_file_id: str | None = None
    error_file_id: str | None = None
    errors: object = None
    metadata: Mapping[str, object] = field(default_factory=dict)
