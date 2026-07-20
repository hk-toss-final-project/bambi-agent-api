"""LLM 응답 공통 파싱 유틸리티를 검증한다."""

from agent.llm.features.parsing import strip_json_fence


def test_strip_json_fence_removes_markdown_fence() -> None:
    """json 언어 태그가 붙은 코드 Fence를 제거한다."""
    raw = "```json\n{\"title\": \"t\"}\n```"

    assert strip_json_fence(raw) == '{"title": "t"}'


def test_strip_json_fence_handles_plain_fence_and_untouched_text() -> None:
    """언어 태그 없는 Fence는 제거하고 일반 텍스트는 그대로 둔다."""
    assert strip_json_fence("```\n[1, 2]\n```") == "[1, 2]"
    assert strip_json_fence('  {"a": 1}  ') == '{"a": 1}'
