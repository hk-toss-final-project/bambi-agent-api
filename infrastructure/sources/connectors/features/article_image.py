"""원본 HTML 메타데이터에서 기사 대표 이미지를 추출한다.

Jina Reader는 기사 본문 정제에만 사용하고, 대표 이미지는 원문 HTML의
Provider 값·Open Graph·Twitter Card·Schema.org·본문 DOM 순서로 결정한다.
직접 URL을 요청하므로 사설 네트워크 접근, 무제한 응답과 리다이렉트를 차단한다.
"""

from __future__ import annotations

import ipaddress
import json
import re
import socket
from collections.abc import Callable, Sequence
from dataclasses import dataclass
from html.parser import HTMLParser
from typing import Any
from urllib.parse import urljoin, urlsplit, urlunsplit

import httpx

from .url import is_probable_content_image_url

_DEFAULT_TIMEOUT_SECONDS = 8.0
_DEFAULT_MAX_HTML_BYTES = 1_500_000
_MAX_REDIRECTS = 4
_MAX_HTTP_UPGRADE_PROBES = 3
_REDIRECT_STATUS_CODES = {301, 302, 303, 307, 308}
_VOID_TAGS = {
    "area",
    "base",
    "br",
    "col",
    "embed",
    "hr",
    "img",
    "input",
    "link",
    "meta",
    "source",
    "track",
    "wbr",
}
_CONTENT_CONTEXT = re.compile(
    r"(?:^|[-_\s])(?:(?:article|story|post)(?:[-_\s]+(?:body|content))?"
    r"|(?:news|view)[-_\s]+(?:body|content))(?:$|[-_\s])",
    flags=re.IGNORECASE,
)
_UI_IMAGE_MARKERS = (
    "logo",
    "icon",
    "avatar",
    "profile",
    "author",
    "reporter",
    "프로필",
    "advert",
    "광고",
    "banner",
    "animation",
    "애니메이션",
    "aichat",
    "global_ani",
    "sprite",
    "tracking",
    "pixel",
)

type HostResolver = Callable[[str], Sequence[str]]


class ArticleImageFetchError(RuntimeError):
    """원본 HTML 이미지 메타데이터 조회 실패 코드와 원인을 보존한다."""

    def __init__(self, error_code: str, message: str) -> None:
        """오류 코드와 사람이 읽을 메시지로 예외를 만든다."""
        super().__init__(message)
        self.error_code = error_code


@dataclass(frozen=True, slots=True)
class ArticleImageMetadata:
    """선택된 기사 대표 이미지와 선택 근거 메타데이터다."""

    url: str
    source: str
    width: int | None = None
    height: int | None = None
    alt: str | None = None
    upgraded_from_http: bool = False


def _dimension(value: object) -> int | None:
    """HTML·JSON-LD 크기 값을 양의 정수로 정규화한다."""
    text = str(value or "").strip()
    if "%" in text:
        return None
    match = re.search(r"\d+", text)
    if match is None:
        return None
    parsed = int(match.group())
    return parsed if parsed > 0 else None


def _srcset_url(value: str) -> str:
    """srcset에서 가장 큰 width·density 후보 URL을 고른다."""
    candidates: list[tuple[float, str]] = []
    for index, part in enumerate(value.split(","), start=1):
        tokens = part.strip().split()
        if not tokens:
            continue
        weight = float(index)
        if len(tokens) > 1:
            descriptor = tokens[-1].lower()
            try:
                weight = float(descriptor.rstrip("wx"))
            except ValueError:
                pass
        candidates.append((weight, tokens[0]))
    return max(candidates, default=(0.0, ""))[1]


def _image_value(value: object) -> tuple[str, int | None, int | None]:
    """Schema.org image 값을 URL과 크기로 변환한다."""
    if isinstance(value, str):
        return value, None, None
    if isinstance(value, list):
        for item in value:
            url, width, height = _image_value(item)
            if url:
                return url, width, height
        return "", None, None
    if isinstance(value, dict):
        url = str(value.get("url") or value.get("contentUrl") or "").strip()
        return url, _dimension(value.get("width")), _dimension(value.get("height"))
    return "", None, None


def _schema_article_images(value: object) -> list[ArticleImageMetadata]:
    """JSON-LD 트리에서 Article 계열 객체의 이미지 후보를 재귀 탐색한다."""
    results: list[ArticleImageMetadata] = []
    if isinstance(value, list):
        for item in value:
            results.extend(_schema_article_images(item))
        return results
    if not isinstance(value, dict):
        return results

    raw_types = value.get("@type") or []
    types = [raw_types] if isinstance(raw_types, str) else list(raw_types)
    if any(str(item).lower().endswith("article") for item in types):
        url, width, height = _image_value(value.get("image"))
        if url:
            results.append(
                ArticleImageMetadata(
                    url=url,
                    source="schema_org",
                    width=width,
                    height=height,
                )
            )
    for child in value.values():
        if isinstance(child, (dict, list)):
            results.extend(_schema_article_images(child))
    return results


class _ArticleImageParser(HTMLParser):
    """HTML head 메타데이터와 기사 본문 이미지 후보를 수집한다."""

    def __init__(self) -> None:
        """메타데이터와 DOM 후보 저장소를 초기화한다."""
        super().__init__(convert_charrefs=True)
        self.metadata: dict[str, list[str]] = {}
        self.schema_images: list[ArticleImageMetadata] = []
        self.article_images: list[ArticleImageMetadata] = []
        self._element_stack: list[tuple[str, bool]] = []
        self._content_depth = 0
        self._json_ld_parts: list[str] | None = None

    def handle_starttag(
        self, tag: str, attrs: list[tuple[str, str | None]]
    ) -> None:
        """시작 태그의 메타데이터·본문 이미지와 Context 진입을 기록한다."""
        lowered_tag = tag.lower()
        values = {key.lower(): str(value or "") for key, value in attrs}
        if lowered_tag == "meta":
            key = (values.get("property") or values.get("name") or "").lower()
            content = values.get("content", "").strip()
            if key and content:
                self.metadata.setdefault(key, []).append(content)
        elif lowered_tag == "script" and "application/ld+json" in values.get(
            "type", ""
        ).lower():
            self._json_ld_parts = []
        elif lowered_tag == "img" and self._content_depth > 0:
            self._append_article_image(values)

        if lowered_tag not in _VOID_TAGS:
            marker_text = " ".join(
                (values.get("id", ""), values.get("class", ""))
            )
            starts_content = lowered_tag == "article" or bool(
                _CONTENT_CONTEXT.search(marker_text)
            )
            self._element_stack.append((lowered_tag, starts_content))
            if starts_content:
                self._content_depth += 1

    def handle_startendtag(
        self, tag: str, attrs: list[tuple[str, str | None]]
    ) -> None:
        """자기 종료 태그를 일반 시작 태그와 같은 규칙으로 처리한다."""
        self.handle_starttag(tag, attrs)
        if tag.lower() not in _VOID_TAGS:
            self.handle_endtag(tag)

    def handle_endtag(self, tag: str) -> None:
        """닫힌 Context를 스택에서 제거하고 JSON-LD를 파싱한다."""
        lowered_tag = tag.lower()
        if lowered_tag == "script" and self._json_ld_parts is not None:
            raw = "".join(self._json_ld_parts).strip()
            self._json_ld_parts = None
            if raw:
                try:
                    self.schema_images.extend(_schema_article_images(json.loads(raw)))
                except (TypeError, ValueError):
                    pass

        for index in range(len(self._element_stack) - 1, -1, -1):
            stack_tag, _ = self._element_stack[index]
            if stack_tag != lowered_tag:
                continue
            removed = self._element_stack[index:]
            del self._element_stack[index:]
            self._content_depth -= sum(1 for _, entered in removed if entered)
            break

    def handle_data(self, data: str) -> None:
        """JSON-LD script 본문을 후속 파싱을 위해 누적한다."""
        if self._json_ld_parts is not None:
            self._json_ld_parts.append(data)

    def _append_article_image(self, values: dict[str, str]) -> None:
        """기사 Context 안 img 태그를 정규화해 후보에 추가한다."""
        url = (
            values.get("data-src")
            or values.get("data-original")
            or _srcset_url(values.get("srcset", ""))
            or values.get("src", "")
        ).strip()
        if not url:
            return
        self.article_images.append(
            ArticleImageMetadata(
                url=url,
                source="article_dom",
                width=_dimension(values.get("width")),
                height=_dimension(values.get("height")),
                alt=values.get("alt") or None,
            )
        )


def _normalized_candidate(
    candidate: ArticleImageMetadata, *, page_url: str
) -> ArticleImageMetadata | None:
    """후보 URL을 HTTPS 절대 경로로 만들고 UI 자산·작은 이미지를 제외한다."""
    url = urljoin(page_url, candidate.url.strip())
    if not is_probable_content_image_url(url):
        return None
    parsed = urlsplit(url)
    upgraded_from_http = parsed.scheme == "http"
    if upgraded_from_http:
        url = urlunsplit(("https", parsed.netloc, parsed.path, parsed.query, parsed.fragment))
    semantic_text = " ".join((url, candidate.alt or "")).lower()
    if any(marker in semantic_text for marker in _UI_IMAGE_MARKERS):
        return None
    if candidate.width is not None and candidate.width < 300:
        return None
    if candidate.height is not None and candidate.height < 200:
        return None
    if candidate.width and candidate.height:
        ratio = candidate.width / candidate.height
        if ratio > 4.0 or ratio < 0.2:
            return None
    return ArticleImageMetadata(
        url=url,
        source=candidate.source,
        width=candidate.width,
        height=candidate.height,
        alt=candidate.alt,
        upgraded_from_http=upgraded_from_http,
    )


def _first_metadata_value(parser: _ArticleImageParser, key: str) -> str:
    """동일 키가 여러 번 나오면 첫 번째 비어 있지 않은 값을 반환한다."""
    return next((value for value in parser.metadata.get(key, []) if value), "")


def extract_article_image_candidates(
    html_text: str,
    *,
    page_url: str,
    provider_image_url: str | None = None,
) -> list[ArticleImageMetadata]:
    """원본 HTML에서 우선순위에 따라 HTTPS 대표 이미지 후보를 만든다.

    Args:
        html_text: 원문 페이지 HTML
        page_url: 상대 이미지 URL을 해석할 최종 페이지 URL
        provider_image_url: NewsAPI 등 Provider가 이미 제공한 이미지 URL

    Returns:
        중복을 제거한 이미지 후보 목록. HTTP 후보는 HTTPS로 승격 표시한다.
    """
    parser = _ArticleImageParser()
    parser.feed(html_text)
    parser.close()

    candidates: list[ArticleImageMetadata] = []
    if provider_image_url:
        candidates.append(
            ArticleImageMetadata(url=provider_image_url, source="provider")
        )

    open_graph_urls = list(
        dict.fromkeys(
            [
                *parser.metadata.get("og:image:secure_url", []),
                *parser.metadata.get("og:image", []),
            ]
        )
    )
    for index, open_graph_url in enumerate(open_graph_urls):
        candidates.append(
            ArticleImageMetadata(
                url=open_graph_url,
                source="open_graph",
                width=(
                    _dimension(_first_metadata_value(parser, "og:image:width"))
                    if index == 0
                    else None
                ),
                height=(
                    _dimension(_first_metadata_value(parser, "og:image:height"))
                    if index == 0
                    else None
                ),
                alt=_first_metadata_value(parser, "og:image:alt") or None,
            )
        )

    twitter_urls = list(
        dict.fromkeys(
            [
                *parser.metadata.get("twitter:image", []),
                *parser.metadata.get("twitter:image:src", []),
            ]
        )
    )
    for twitter_url in twitter_urls:
        candidates.append(
            ArticleImageMetadata(
                url=twitter_url,
                source="twitter_card",
                alt=_first_metadata_value(parser, "twitter:image:alt") or None,
            )
        )
    candidates.extend(parser.schema_images)

    normalized_article = [
        normalized
        for candidate in parser.article_images
        if (normalized := _normalized_candidate(candidate, page_url=page_url))
        is not None
    ]
    normalized_article.sort(
        key=lambda item: (item.width or 0) * (item.height or 0), reverse=True
    )

    normalized_candidates: list[ArticleImageMetadata] = []
    seen_urls: set[str] = set()
    for candidate in candidates:
        normalized = _normalized_candidate(candidate, page_url=page_url)
        if normalized is None or normalized.url in seen_urls:
            continue
        seen_urls.add(normalized.url)
        normalized_candidates.append(normalized)
    for normalized in normalized_article:
        if normalized.url in seen_urls:
            continue
        seen_urls.add(normalized.url)
        normalized_candidates.append(normalized)
    return normalized_candidates


def extract_article_image_metadata(
    html_text: str,
    *,
    page_url: str,
    provider_image_url: str | None = None,
) -> ArticleImageMetadata | None:
    """원본 HTML의 우선순위가 가장 높은 HTTPS 대표 이미지 후보를 반환한다."""
    return next(
        iter(
            extract_article_image_candidates(
                html_text,
                page_url=page_url,
                provider_image_url=provider_image_url,
            )
        ),
        None,
    )


def _default_host_resolver(host: str) -> list[str]:
    """호스트의 IPv4·IPv6 주소를 중복 없이 조회한다."""
    try:
        addresses = socket.getaddrinfo(host, None, type=socket.SOCK_STREAM)
    except socket.gaierror as error:
        raise ArticleImageFetchError(
            "dns_error", f"기사 URL 호스트를 확인할 수 없습니다: {host}"
        ) from error
    return list(dict.fromkeys(str(item[4][0]) for item in addresses))


def _ensure_public_http_url(url: str, *, host_resolver: HostResolver) -> None:
    """HTTP(S) URL이 공개 네트워크 호스트만 가리키는지 검증한다."""
    parsed = urlsplit(url)
    if parsed.scheme not in {"http", "https"} or not parsed.hostname:
        raise ArticleImageFetchError("unsafe_url", f"허용하지 않는 기사 URL입니다: {url}")
    if parsed.username or parsed.password:
        raise ArticleImageFetchError(
            "unsafe_url", "인증정보가 포함된 기사 URL은 요청하지 않습니다."
        )

    try:
        literal = ipaddress.ip_address(parsed.hostname)
        addresses = [literal]
    except ValueError:
        addresses = [ipaddress.ip_address(item) for item in host_resolver(parsed.hostname)]
    if not addresses or any(not address.is_global for address in addresses):
        raise ArticleImageFetchError(
            "unsafe_url", f"공개 네트워크가 아닌 기사 URL은 요청하지 않습니다: {url}"
        )


def _probe_upgraded_image(
    client: httpx.Client,
    candidate: ArticleImageMetadata,
    *,
    host_resolver: HostResolver,
) -> bool:
    """HTTP에서 승격한 HTTPS 후보가 실제 이미지로 응답하는지 제한적으로 확인한다."""
    current_url = candidate.url
    headers = {
        "Accept": "image/avif,image/webp,image/*,*/*;q=0.8",
        "User-Agent": "AlphaCatcher/1.0",
    }
    try:
        for redirect_count in range(_MAX_REDIRECTS + 1):
            if urlsplit(current_url).scheme != "https":
                return False
            _ensure_public_http_url(current_url, host_resolver=host_resolver)
            with client.stream("GET", current_url, headers=headers) as response:
                if response.status_code in _REDIRECT_STATUS_CODES:
                    location = response.headers.get("location")
                    if not location or redirect_count >= _MAX_REDIRECTS:
                        return False
                    current_url = urljoin(current_url, location)
                    continue
                if response.status_code >= 400:
                    return False
                return response.headers.get("content-type", "").lower().startswith(
                    "image/"
                )
    except (ArticleImageFetchError, httpx.HTTPError):
        return False
    return False


def _first_usable_candidate(
    client: httpx.Client,
    candidates: Sequence[ArticleImageMetadata],
    *,
    host_resolver: HostResolver,
) -> ArticleImageMetadata | None:
    """HTTPS 후보를 순회하며 HTTP 승격 후보만 실제 응답을 검증해 선택한다."""
    upgrade_probes = 0
    for candidate in candidates:
        if not candidate.upgraded_from_http:
            return candidate
        if upgrade_probes >= _MAX_HTTP_UPGRADE_PROBES:
            continue
        upgrade_probes += 1
        if _probe_upgraded_image(
            client,
            candidate,
            host_resolver=host_resolver,
        ):
            return candidate
    return None


def fetch_article_image_metadata(
    url: str,
    *,
    provider_image_url: str | None = None,
    timeout: float = _DEFAULT_TIMEOUT_SECONDS,
    max_html_bytes: int = _DEFAULT_MAX_HTML_BYTES,
    transport: httpx.BaseTransport | None = None,
    host_resolver: HostResolver | None = None,
) -> ArticleImageMetadata | None:
    """원본 URL의 HTML을 제한적으로 읽어 대표 이미지 메타데이터를 추출한다.

    HTTPS Provider 이미지는 즉시 반환하고, HTTP 이미지는 HTTPS 승격이 실제 이미지
    응답인지 확인한다. 승격이나 후보가 실패하면 원문 HTML의 다음 후보를 계속
    탐색한다. 직접 요청할 때는 매 리다이렉트의 공개 IP 여부를 확인한다.

    Args:
        url: 기사 원문 URL
        provider_image_url: Provider 응답에 포함된 이미지 URL
        timeout: HTTP 요청 제한 시간(초)
        max_html_bytes: 읽을 HTML 최대 바이트 수
        transport: 테스트용 HTTP Transport
        host_resolver: 테스트 또는 정책 주입용 DNS 조회 함수

    Returns:
        대표 이미지 메타데이터. 적합한 이미지가 없으면 ``None``.

    Raises:
        ArticleImageFetchError: URL·DNS·HTTP·응답 크기 검증에 실패한 경우
    """
    resolver = host_resolver or _default_host_resolver
    current_url = url
    headers = {
        "Accept": "text/html,application/xhtml+xml;q=0.9",
        "User-Agent": "AlphaCatcher/1.0",
    }
    try:
        with httpx.Client(
            timeout=timeout, transport=transport, follow_redirects=False
        ) as client:
            provider_candidates = extract_article_image_candidates(
                "", page_url=url, provider_image_url=provider_image_url
            )
            provider = _first_usable_candidate(
                client,
                provider_candidates,
                host_resolver=resolver,
            )
            if provider is not None:
                return provider

            for redirect_count in range(_MAX_REDIRECTS + 1):
                _ensure_public_http_url(current_url, host_resolver=resolver)
                with client.stream("GET", current_url, headers=headers) as response:
                    if response.status_code in _REDIRECT_STATUS_CODES:
                        location = response.headers.get("location")
                        if not location or redirect_count >= _MAX_REDIRECTS:
                            raise ArticleImageFetchError(
                                "redirect_error", "기사 URL 리다이렉트가 유효하지 않습니다."
                            )
                        current_url = urljoin(current_url, location)
                        continue
                    response.raise_for_status()
                    content_type = response.headers.get("content-type", "").lower()
                    if content_type and not (
                        content_type.startswith("text/html")
                        or content_type.startswith("application/xhtml+xml")
                    ):
                        return None
                    body = bytearray()
                    for chunk in response.iter_bytes():
                        body.extend(chunk)
                        if len(body) > max_html_bytes:
                            raise ArticleImageFetchError(
                                "response_too_large",
                                f"기사 HTML이 {max_html_bytes}바이트 제한을 넘었습니다.",
                            )
                    encoding = response.encoding or "utf-8"
                    html_text = bytes(body).decode(encoding, errors="replace")
                    candidates = extract_article_image_candidates(
                        html_text,
                        page_url=current_url,
                    )
                    return _first_usable_candidate(
                        client,
                        candidates,
                        host_resolver=resolver,
                    )
    except ArticleImageFetchError:
        raise
    except httpx.HTTPError as error:
        raise ArticleImageFetchError(
            "request_failed", f"기사 이미지 메타데이터 조회에 실패했습니다: {error}"
        ) from error
    return None
