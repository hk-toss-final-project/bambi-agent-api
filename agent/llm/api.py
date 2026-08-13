"""기능 영역의 공개 facade.

구현 모듈의 기능 함수를 안정적인 import 경로로 다시 노출한다.
"""

from .features.client import (
    LlmCompletion,
    LlmCallObservation,
    capture_llm_calls,
    complete,
    complete_with_usage,
    is_openai_action_required_error,
    is_retryable_openai_error,
    retry_after_seconds_from_error,
    response_headers_from_value,
)
from .features.embedding_client import embed_texts, get_embedding_client
from .features.batch_client import (
    BatchProvider,
    OpenAIBatchProvider,
    ProviderBatchSubmission,
    build_batch_jsonl,
    parse_batch_jsonl,
)
from .features.parsing import strip_json_fence
from .features.tool_loop import (
    ToolCallRecord,
    ToolLoopResult,
    ToolSpec,
    run_tool_loop,
)
from .features.usage import (
    LlmUsageContext,
    classify_llm_workload,
    current_llm_usage_context,
    llm_usage_context,
    llm_usage_metadata_from_job,
)

__all__ = [
    "LlmCompletion",
    "LlmCallObservation",
    "capture_llm_calls",
    "complete",
    "complete_with_usage",
    "is_openai_action_required_error",
    "is_retryable_openai_error",
    "retry_after_seconds_from_error",
    "response_headers_from_value",
    "embed_texts",
    "get_embedding_client",
    "BatchProvider",
    "OpenAIBatchProvider",
    "ProviderBatchSubmission",
    "build_batch_jsonl",
    "parse_batch_jsonl",
    "strip_json_fence",
    "ToolCallRecord",
    "ToolLoopResult",
    "ToolSpec",
    "run_tool_loop",
    "LlmUsageContext",
    "classify_llm_workload",
    "current_llm_usage_context",
    "llm_usage_context",
    "llm_usage_metadata_from_job",
]
