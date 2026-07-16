"""사용자 URL 목록 텍스트 파일을 검증하고 로딩한다."""

from pathlib import Path
from urllib.parse import urlparse


def load_user_urls(path: Path) -> list[str]:
    """텍스트 파일에서 중복 없는 HTTP(S) URL 목록을 순서대로 읽는다.

    빈 줄과 `#`으로 시작하는 주석은 무시한다.

    Args:
        path: URL 목록 텍스트 파일 경로

    Returns:
        입력 파일의 순서를 보존한 URL 목록

    Raises:
        ValueError: URL이 없거나 형식이 잘못됐거나 중복된 경우
    """
    urls = [
        line
        for raw_line in path.read_text(encoding="utf-8").splitlines()
        if (line := raw_line.strip()) and not line.startswith("#")
    ]
    if not urls:
        raise ValueError(f"URL이 없습니다: {path}")

    invalid_urls = [
        url
        for url in urls
        if (parsed := urlparse(url)).scheme not in {"http", "https"}
        or not parsed.netloc
    ]
    if invalid_urls:
        raise ValueError(f"HTTP(S) URL이 아닙니다: {invalid_urls[0]}")
    if len(urls) != len(set(urls)):
        raise ValueError(f"중복 URL이 있습니다: {path}")
    return urls
