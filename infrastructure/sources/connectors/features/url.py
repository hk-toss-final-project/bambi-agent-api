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


def extract_jina_image(text: str) -> str | None:
    """Jina 응답에서 대표 이미지로 쓸 수 있는 HTTP(S) URL을 하나 고른다.

    Jina의 ``Image N:`` 헤더와 본문 Markdown 이미지를 순서대로 확인한다.
    로고·아이콘·트래킹 픽셀처럼 대표 이미지가 아닌 흔한 후보는 제외하고,
    확장자가 명확한 이미지 URL을 우선한다. 이미지가 없거나 안전한 외부 URL로
    해석할 수 없으면 ``None``을 반환한다.

    Args:
        text: Jina Reader의 헤더 포함 원문 응답

    Returns:
        대표 이미지 HTTP(S) URL. 적합한 후보가 없으면 ``None``
    """
    candidates = re.findall(r"^Image \d+:\s*(https?://\S+)", text, flags=re.MULTILINE)
    candidates += re.findall(r"!\[[^\]]*\]\((https?://[^)]+)\)", text)
    preferred: list[str] = []
    fallback: list[str] = []
    seen: set[str] = set()
    for candidate in candidates:
        url = html.unescape(candidate).strip().strip("<>\"'")
        if url in seen:
            continue
        seen.add(url)
        parsed = urlsplit(url)
        if parsed.scheme not in {"http", "https"} or not parsed.netloc:
            continue
        lowered = url.lower()
        if any(
            marker in lowered
            for marker in ("logo", "icon", "sprite", "1x1", "blank", "avatar", "pixel")
        ):
            continue
        if re.search(r"\.(?:avif|gif|jpe?g|png|webp)(?:[?#]|$)", lowered):
            preferred.append(url)
        else:
            fallback.append(url)
    return next(iter(preferred or fallback), None)


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
        image_url=extract_jina_image(text),
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
