"""기능 구현 모듈.

COL-011 기능의 실제 구현 위치와, 사용자 입력 URL 본문을
Jina Reader(r.jina.ai)로 정제해 가져오는 수집 함수를 제공한다.
"""

import html
import os
import re
from dataclasses import dataclass
from urllib.parse import urlsplit

import httpx

from shared.contracts import FeatureRequest, FeatureResult

# Jina Reader 기본 URL과 조회 타임아웃(초).
_JINA_READER_BASE_URL = "https://r.jina.ai"
_JINA_TIMEOUT_SECONDS = 30.0

# 기사 본문보다 앞뒤에 반복되는 사이트 UI 이미지 URL 표식이다. 본문 범위 제한에
# 실패하더라도 이런 자산이 대표 이미지로 발행되지 않게 하는 마지막 가드다.
_PAGE_CHROME_IMAGE_MARKERS = (
    "logo",
    "icon",
    "/ico",
    "_ico",
    "sprite",
    "1x1",
    "blank",
    "avatar",
    "/profile/",
    "/author/",
    "pixel",
    "banner",
    "/btn",
    "btn_",
    "/arrow",
    "arrow_",
    "favicon",
    "placeholder",
    "loading",
    "aichat",
    "global_ani",
    "/column/",
)


class JinaReadError(RuntimeError):
    """Jina Reader 수집 실패의 원인 코드와 메시지를 보존하는 예외."""

    def __init__(self, error_code: str, message: str) -> None:
        """오류 코드와 사람이 읽을 메시지로 예외를 만든다."""
        super().__init__(message)
        self.error_code = error_code


@dataclass(frozen=True, slots=True)
class JinaReadResult:
    """Jina Reader가 정제한 URL 본문 스냅샷 한 건."""

    requested_url: str
    resolved_url: str
    title: str
    published_time: str | None
    markdown: str
    image_url: str | None = None


def find_article_body_offset(markdown: str, title: str) -> int | None:
    """Jina Markdown에서 기사 제목이 시작되는 위치를 찾는다.

    제목의 앞 12개 영숫자·한글 사이에 문장부호가 끼는 것을 허용해, 원문과
    Jina 헤더의 따옴표·말줄임표 표기가 달라도 본문 시작점을 찾는다.

    Args:
        markdown: Jina Reader가 반환한 Markdown 본문
        title: Jina 헤더에서 읽은 기사 제목

    Returns:
        기사 제목 시작 위치. 신뢰할 수 있는 제목 위치가 없으면 None.
    """
    letters = re.findall(r"[0-9A-Za-z가-힣]", title)[:12]
    if len(letters) < 6:
        return None
    pattern = r"[^0-9A-Za-z가-힣]{0,4}".join(re.escape(char) for char in letters)
    match = re.search(pattern, markdown)
    return match.start() if match else None


def is_probable_content_image_url(value: str) -> bool:
    """URL이 사이트 UI 자산이 아닌 HTTP(S) 본문 이미지 후보인지 판정한다."""
    url = html.unescape(value).strip().strip("<>\"'")
    parsed = urlsplit(url)
    if parsed.scheme not in {"http", "https"} or not parsed.netloc:
        return False
    lowered = url.lower()
    return not any(marker in lowered for marker in _PAGE_CHROME_IMAGE_MARKERS)


def extract_jina_image(text: str, *, title: str = "") -> str | None:
    """Jina 응답에서 대표 이미지로 쓸 수 있는 HTTP(S) URL을 하나 고른다.

    Jina 헤더의 기사 제목을 본문에서 찾은 뒤 그 이후 Markdown 이미지만 확인한다.
    제목을 찾지 못하면 메뉴·배너를 본문으로 오인하지 않도록 ``None``을 반환한다.
    헤더가 없는 일반 Markdown은 전체를 대상으로 하되 UI 자산 URL은 제외한다.

    Args:
        text: Jina Reader의 헤더 포함 원문 응답 또는 일반 Markdown
        title: 이미 파싱한 기사 제목. 비면 Jina 헤더에서 읽는다.

    Returns:
        대표 이미지 HTTP(S) URL. 적합한 후보가 없으면 ``None``
    """
    marker = "Markdown Content:"
    if marker in text:
        header_block, markdown = text.split(marker, 1)
        if not title:
            for line in header_block.splitlines():
                key, _, value = line.partition(":")
                if key == "Title":
                    title = value.strip()
                    break
    else:
        markdown = text

    if title:
        offset = find_article_body_offset(markdown, title)
        if offset is None:
            return None
        markdown = markdown[offset:]

    candidates = re.findall(
        r"^Image \d+:\s*(https?://\S+)", markdown, flags=re.MULTILINE
    )
    candidates += re.findall(r"!\[[^\]]*\]\((https?://[^)]+)\)", markdown)
    preferred: list[str] = []
    fallback: list[str] = []
    seen: set[str] = set()
    for candidate in candidates:
        url = html.unescape(candidate).strip().strip("<>\"'")
        if url in seen:
            continue
        seen.add(url)
        if not is_probable_content_image_url(url):
            continue
        lowered = url.lower()
        if re.search(r"\.(?:avif|gif|jpe?g|png|webp)(?:[?#]|$)", lowered):
            preferred.append(url)
        else:
            fallback.append(url)
    return next(iter(preferred or fallback), None)


def resolve_article_image(
    *, markdown: str, title: str, cached_url: str | None = None
) -> str | None:
    """저장된 기사 본문과 기존 캐시에서 안전한 대표 이미지를 결정한다.

    저장 시점의 선택 규칙이 메뉴·배너를 집어 넣었을 수 있으므로 Markdown에서
    기사 제목 이후 이미지를 다시 계산한다. 본문에 이미지가 없을 때만 사이트 UI
    자산이 아닌 기존 캐시를 유지한다.

    Args:
        markdown: 저장된 Jina Markdown 본문
        title: 저장된 기사 제목
        cached_url: 과거에 선택해 저장한 대표 이미지 URL

    Returns:
        다시 계산한 본문 이미지 또는 안전한 기존 캐시. 둘 다 없으면 ``None``.
    """
    if cached_url and is_probable_content_image_url(cached_url):
        return html.unescape(cached_url).strip().strip("<>\"'")
    return extract_jina_image(markdown, title=title)


def parse_jina_reader_response(text: str, *, requested_url: str) -> JinaReadResult:
    """Jina Reader 텍스트 응답을 메타데이터 헤더와 Markdown 본문으로 분리한다.

    응답은 'Title: ...', 'URL Source: ...', 'Published Time: ...' 헤더 뒤에
    'Markdown Content:' 구분자와 본문이 이어진다. 구분자가 없으면 전체를
    본문으로 간주하고, 본문이 비어 있으면 실패로 처리한다.

    Args:
        text: Jina Reader의 text/plain 응답 전문
        requested_url: 수집을 요청한 원래 URL (헤더 누락 시 대체값)

    Returns:
        제목, 리다이렉트가 반영된 최종 URL, 게시 시각, Markdown 본문

    Raises:
        JinaReadError: 본문이 비어 있는 경우
    """
    marker = "Markdown Content:"
    title = ""
    resolved_url = ""
    published_time: str | None = None

    if marker in text:
        header_block, markdown = text.split(marker, 1)
        for line in header_block.splitlines():
            key, _, value = line.partition(":")
            value = value.strip()
            if key == "Title":
                title = value
            elif key == "URL Source":
                resolved_url = value
            elif key == "Published Time":
                published_time = value or None
    else:
        markdown = text

    markdown = markdown.strip()
    if not markdown:
        raise JinaReadError(
            "empty_content", f"Jina Reader 응답에 본문이 없습니다: {requested_url}"
        )
    return JinaReadResult(
        requested_url=requested_url,
        resolved_url=resolved_url or requested_url,
        title=title or requested_url,
        published_time=published_time,
        markdown=markdown,
        image_url=extract_jina_image(text, title=title),
    )


def fetch_url_raw_via_jina(
    url: str,
    *,
    timeout: float = _JINA_TIMEOUT_SECONDS,
    api_key: str | None = None,
    transport: httpx.BaseTransport | None = None,
) -> str:
    """URL 본문을 Jina Reader로 수집해 헤더 포함 원문 텍스트로 반환한다.

    Jina 인증·HTTP 오류 처리를 이 함수 한 곳에 모은다. 구조화된 결과가
    필요하면 fetch_url_via_jina를, 'Image N:' 헤더 등 원문 전체가 필요하면
    (키워드 비서의 대표 이미지 추출 등) 이 함수를 사용한다.

    Args:
        url: 수집할 대상 URL
        timeout: HTTP 타임아웃(초)
        api_key: Jina API Key. 생략하면 JINA_API_KEY 환경변수를 사용하고,
            둘 다 없으면 무인증 무료 호출로 요청한다.
        transport: 테스트에서 네트워크를 대체할 httpx Transport

    Returns:
        Jina Reader의 text/plain 응답 전문

    Raises:
        JinaReadError: 네트워크 오류, HTTP 4xx/5xx
    """
    key = api_key if api_key is not None else (os.getenv("JINA_API_KEY") or None)
    headers = {"Authorization": f"Bearer {key}"} if key else {}
    try:
        with httpx.Client(
            timeout=timeout, transport=transport, follow_redirects=True
        ) as client:
            response = client.get(f"{_JINA_READER_BASE_URL}/{url}", headers=headers)
    except httpx.HTTPError as error:
        raise JinaReadError(
            "network_error", f"Jina Reader 호출에 실패했습니다: {error}"
        ) from error
    if response.status_code >= 400:
        raise JinaReadError(
            f"http_{response.status_code}",
            f"Jina Reader가 오류 상태를 반환했습니다: {response.status_code} ({url})",
        )
    return response.text


def fetch_url_via_jina(
    url: str,
    *,
    timeout: float = _JINA_TIMEOUT_SECONDS,
    api_key: str | None = None,
    transport: httpx.BaseTransport | None = None,
) -> JinaReadResult:
    """URL 본문을 Jina Reader로 수집해 정제된 Markdown 스냅샷으로 반환한다.

    Args:
        url: 수집할 대상 URL
        timeout: HTTP 타임아웃(초)
        api_key: Jina API Key. 생략하면 JINA_API_KEY 환경변수를 사용하고,
            둘 다 없으면 무인증 무료 호출로 요청한다.
        transport: 테스트에서 네트워크를 대체할 httpx Transport

    Returns:
        파싱이 끝난 JinaReadResult

    Raises:
        JinaReadError: 네트워크 오류, HTTP 4xx/5xx, 빈 본문
    """
    raw = fetch_url_raw_via_jina(
        url, timeout=timeout, api_key=api_key, transport=transport
    )
    return parse_jina_reader_response(raw, requested_url=url)


async def col_011(request: FeatureRequest) -> FeatureResult:
    """[COL-011] 직접 URL 수집.

    관리자가 지정한 URL의 데이터를 수집한다.
    """
    raise NotImplementedError("[COL-011] 기능 구현이 필요합니다.")
