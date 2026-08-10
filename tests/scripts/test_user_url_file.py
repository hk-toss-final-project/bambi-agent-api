"""사용자 URL 목록 파일 로더의 입력 검증을 테스트한다."""

import subprocess
import sys
from pathlib import Path

import pytest

from scripts.user_url_file import load_user_urls

PROJECT_ROOT = Path(__file__).parents[2]


def test_load_user_urls_preserves_order_and_ignores_blank_lines_and_comments(
    tmp_path: Path,
) -> None:
    """빈 줄과 주석을 제외하고 URL 입력 순서를 보존하는지 검증한다."""
    url_file = tmp_path / "url.txt"
    url_file.write_text(
        "# 개발 URL\n\nhttps://example.com/first\n  https://example.com/second  \n",
        encoding="utf-8",
    )

    assert load_user_urls(url_file) == [
        "https://example.com/first",
        "https://example.com/second",
    ]


@pytest.mark.parametrize(
    "content",
    ["ftp://example.com/file", "example.com/no-scheme", "https:///no-host"],
)
def test_load_user_urls_rejects_non_http_urls(tmp_path: Path, content: str) -> None:
    """HTTP(S) 형식이 아닌 입력을 거부하는지 검증한다."""
    url_file = tmp_path / "url.txt"
    url_file.write_text(content, encoding="utf-8")

    with pytest.raises(ValueError, match=r"HTTP\(S\) URL이 아닙니다"):
        load_user_urls(url_file)


def test_load_user_urls_rejects_duplicates(tmp_path: Path) -> None:
    """동일 URL이 두 번 포함된 입력을 거부하는지 검증한다."""
    url_file = tmp_path / "url.txt"
    url_file.write_text(
        "https://example.com/same\nhttps://example.com/same\n",
        encoding="utf-8",
    )

    with pytest.raises(ValueError, match="중복 URL"):
        load_user_urls(url_file)


def test_url_ingest_cli_requires_explicit_user_and_source() -> None:
    """URL 수집 CLI가 제거된 더미 기본값 없이 명시적 입력을 요구한다."""
    result = subprocess.run(
        [sys.executable, str(PROJECT_ROOT / "scripts" / "ingest_user_urls.py")],
        cwd=PROJECT_ROOT,
        check=False,
        capture_output=True,
        text=True,
    )

    assert result.returncode == 2
    assert "--user-id" in result.stderr


def test_build_wiki_cli_requires_explicit_user() -> None:
    """강제 Wiki Build CLI가 제거된 더미 사용자 대신 사용자 ID를 요구한다."""
    result = subprocess.run(
        [sys.executable, str(PROJECT_ROOT / "scripts" / "build_wiki_now.py")],
        cwd=PROJECT_ROOT,
        check=False,
        capture_output=True,
        text=True,
    )

    assert result.returncode == 2
    assert "--user-id" in result.stderr
