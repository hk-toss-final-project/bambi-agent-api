"""LLM 응답 텍스트 공통 파싱 유틸리티.

JSON 응답을 Markdown 코드 Fence로 감싸는 모델 습관을 도메인마다 중복
처리하지 않도록 한 곳에서 제거한다.
"""


def strip_json_fence(value: str) -> str:
    """LLM JSON 응답을 감싼 Markdown 코드 Fence를 제거한다."""
    text = value.strip()
    if text.startswith("```"):
        text = text.removeprefix("```json").removeprefix("```").strip()
        text = text.removesuffix("```").strip()
    return text
