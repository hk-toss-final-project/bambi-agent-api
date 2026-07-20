"""계층 공통 콘텐츠 무결성 Hash 유틸리티.

agent(Vault 렌더링)와 infrastructure(원본·문서 저장)가 같은 Hash 규칙을
쓰도록 한 곳에서 정의한다.
"""

import hashlib


def compute_content_hash(content: str) -> str:
    """문서 본문의 64자 SHA-256 무결성 Hash를 계산한다."""
    return hashlib.sha256(content.encode("utf-8")).hexdigest()
