"""LLM 요약 헬퍼.

YouTube 자막이나 기사 본문을 받아 한국어 요약을 생성한다. 실제 LLM(ChatOpenAI)을
호출하므로 OPENAI_API_KEY가 필요하며, 네트워크 경계를 이 모듈로 모아 테스트에서
쉽게 대체할 수 있게 한다.
"""

from __future__ import annotations

_SYSTEM_PROMPT = (
    "너는 콘텐츠를 간결하게 요약하는 한국어 비서다. "
    "제공된 텍스트에 있는 내용만 사용하고, 없는 사실을 지어내지 않는다. "
    "핵심을 3~5개의 불릿으로 정리한다."
)

# ChatOpenAI 클라이언트를 모델별로 한 번만 생성해 재사용한다.
_clients: dict[str, object] = {}
# 요약 입력이 지나치게 길면 비용·지연이 커지므로 상한 문자수로 자른다.
_MAX_INPUT_CHARS = 8000


def _get_client(model: str) -> object:
    """모델 이름에 해당하는 ChatOpenAI 클라이언트를 반환한다."""
    if model not in _clients:
        from langchain_openai import ChatOpenAI

        _clients[model] = ChatOpenAI(model=model, temperature=0.3)
    return _clients[model]


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

    client = _get_client(model)
    response = client.invoke(
        [
            ("system", _SYSTEM_PROMPT),
            ("human", f"{instruction}\n\n---\n{trimmed}"),
        ]
    )
    return str(response.content).strip()
