"""기능 영역의 공개 facade.

구현 모듈의 기능 함수를 안정적인 import 경로로 다시 노출한다.
"""

from .features.client import (
    LlmCompletion,
    LlmCallObservation,
    capture_llm_calls,
    complete,
    complete_with_usage,
    is_retryable_openai_error,
    retry_after_seconds_from_error,
    response_headers_from_value,
)
from .features.completion import llm_001, llm_002, llm_003
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
from .features.tools import llm_004, llm_005
from .features.routing import llm_006, llm_007, llm_008, llm_019
from .features.budgets import llm_009
from .features.context import llm_010, llm_011
from .features.cache import llm_012
from .features.resilience import llm_013, llm_014
from .features.usage import llm_015, llm_016
from .features.safety import llm_017, llm_018

__all__ = [
    "LlmCompletion",
    "LlmCallObservation",
    "capture_llm_calls",
    "complete",
    "complete_with_usage",
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
    "llm_001",
    "llm_002",
    "llm_003",
    "llm_004",
    "llm_005",
    "llm_006",
    "llm_007",
    "llm_008",
    "llm_019",
    "llm_009",
    "llm_010",
    "llm_011",
    "llm_012",
    "llm_013",
    "llm_014",
    "llm_015",
    "llm_016",
    "llm_017",
    "llm_018",
]
