"""기능 영역의 공개 facade.

구현 모듈의 기능 함수를 안정적인 import 경로로 다시 노출한다.
"""

from .features.chunking import chunk_wiki_markdown, pwe_001, pwe_002

__all__ = [
    "pwe_001",
    "pwe_002",
]
