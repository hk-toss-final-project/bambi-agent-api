"""LLM 요약 헬퍼.

YouTube 자막이나 기사 본문을 받아 한국어 요약을 생성한다. 실제 호출은 공유
LLM 클라이언트(agent/llm — 재시도·백오프·Timeout 내장)에 위임하고, 이 모듈은
비서 기능이 대체하기 쉬운 경계(complete·summarize_text 심볼)만 유지한다.
테스트에서 이 함수들만 바꾸면 실제 호출을 막을 수 있다.
"""

from __future__ import annotations

from agent.llm.api import complete as _shared_complete

_SYSTEM_PROMPT = (
    "너는 콘텐츠를 간결하게 요약하는 한국어 비서다. "
    "제공된 텍스트에 있는 내용만 사용하고, 없는 사실을 지어내지 않는다. "
    "핵심을 3~5개의 불릿으로 정리한다."
)

# 요약 입력이 지나치게 길면 비용·지연이 커지므로 상한 문자수로 자른다.
_MAX_INPUT_CHARS = 8000


def complete(system_prompt: str, user_prompt: str, model: str = "gpt-4.1-mini") -> str:
    """system·user 프롬프트로 Chat Completion을 호출해 텍스트를 반환한다.

    요약(summarize_text) 외에 보고서 생성 등 임의의 프롬프트를 쓰는 기능이 공통으로
    사용하는 저수준 LLM 호출 경계다. 테스트에서 이 함수만 대체하면 실제 호출을 막을 수
    있다.
    """
    if not user_prompt.strip():
        return ""
    return _shared_complete(system_prompt, user_prompt, model=model).strip()


def summarize_text(text: str, instruction: str, model: str = "gpt-4.1-mini") -> str:
    """주어진 텍스트를 지시에 맞게 요약한다.

    Args:
        text: 요약 대상 원문 (자막, 기사 본문 등)
        instruction: 요약 방식을 지시하는 문장
        model: 사용할 OpenAI 모델 이름

    Returns:
        한국어 요약 문자열
    """
    trimmed = text.strip()[:_MAX_INPUT_CHARS]
    if not trimmed:
        return ""
    return complete(_SYSTEM_PROMPT, f"{instruction}\n\n---\n{trimmed}", model=model)
