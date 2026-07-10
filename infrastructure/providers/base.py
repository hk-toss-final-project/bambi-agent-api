"""외부 AI Provider를 교체 가능하게 만드는 공통 인터페이스."""

from collections.abc import Mapping, Sequence
from typing import Protocol


class LlmProvider(Protocol):
    """텍스트·대화·구조화 생성을 제공하는 LLM 인터페이스."""

    async def complete(
        self,
        messages: Sequence[Mapping[str, object]],
        *,
        model: str,
        max_tokens: int,
    ) -> str:
        """메시지와 실행 설정을 받아 LLM 생성 결과를 반환한다."""
        ...


class EmbeddingProvider(Protocol):
    """문서와 Chunk를 Vector로 변환하는 Embedding 인터페이스."""

    async def embed(self, texts: Sequence[str], *, model: str) -> list[list[float]]:
        """입력 텍스트 목록의 Embedding Vector를 생성한다."""
        ...


class ImageProvider(Protocol):
    """콘텐츠용 이미지 자료를 생성하는 Provider 인터페이스."""

    async def generate(self, prompt: str, *, model: str) -> bytes:
        """이미지 Prompt와 모델 설정으로 이미지 바이너리를 생성한다."""
        ...
