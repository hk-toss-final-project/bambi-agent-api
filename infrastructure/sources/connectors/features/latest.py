"""Naver·NewsAPI·GDELT·Google News RSS 최신 정보 검색 Connector.

서로 다른 외부 뉴스 API 응답을 제목, URL, 게시 시각, 설명과 Provider를 갖는
공통 LatestArticle 모델로 정규화한다.
"""

import html
import re
from dataclasses import dataclass
from datetime import UTC, datetime
from email.utils import parsedate_to_datetime
from typing import Protocol
from xml.etree import ElementTree

import httpx

_HTML_TAG = re.compile(r"<[^>]+>")


class LatestProviderError(RuntimeError):
    """최신 정보 Provider 실패 코드와 안전한 메시지를 보존하는 예외."""

    def __init__(self, provider: str, error_code: str, message: str) -> None:
        """Provider, 오류 코드와 사용자에게 노출 가능한 메시지를 저장한다."""
        super().__init__(message)
        self.provider = provider
        self.error_code = error_code


@dataclass(frozen=True, slots=True)
class LatestArticle:
    """외부 Provider에서 정규화한 최신 문서 한 건."""

    provider: str
    title: str
    url: str
    description: str
    published_at: datetime | None = None
    source_name: str | None = None
    language: str | None = None
    # 원본 발행처 URL. Google News처럼 url이 리다이렉트 주소인 Provider에서
    # 소스 신뢰도(도메인 가중치) 판정에 쓴다. 알 수 없으면 None.
    source_url: str | None = None


class LatestInformationProvider(Protocol):
    """키워드로 최신 문서를 검색하는 Provider 계약."""

    name: str

    async def search(
        self, *, query: str, limit: int, language: str | None
    ) -> list[LatestArticle]:
        """관련도·최신성 순서의 정규화된 문서를 반환한다."""
        ...


def _clean_text(value: object) -> str:
    """외부 응답의 HTML Entity와 간단한 Tag를 제거한다."""
    text = html.unescape(str(value or ""))
    return _HTML_TAG.sub("", text).strip()


def _iso_datetime(value: object) -> datetime | None:
    """ISO 또는 GDELT 시각 값을 timezone 포함 datetime으로 변환한다."""
    text = str(value or "").strip()
    if not text:
        return None
    try:
        if re.fullmatch(r"\d{8}T\d{6}Z", text):
            return datetime.strptime(text, "%Y%m%dT%H%M%SZ").replace(tzinfo=UTC)
        parsed = datetime.fromisoformat(text.replace("Z", "+00:00"))
        return parsed if parsed.tzinfo else parsed.replace(tzinfo=UTC)
    except ValueError:
        return None


class NaverNewsProvider:
    """Naver 검색 API의 최신 뉴스 결과를 정규화한다."""

    name = "naver"

    def __init__(
        self,
        client_id: str,
        client_secret: str,
        *,
        transport: httpx.AsyncBaseTransport | None = None,
    ) -> None:
        """Naver 인증정보와 테스트용 HTTP Transport를 저장한다."""
        self._client_id = client_id
        self._client_secret = client_secret
        self._transport = transport

    async def search(
        self, *, query: str, limit: int, language: str | None
    ) -> list[LatestArticle]:
        """Naver 뉴스 검색 결과를 게시일 내림차순으로 반환한다."""
        headers = {
            "X-Naver-Client-Id": self._client_id,
            "X-Naver-Client-Secret": self._client_secret,
        }
        try:
            async with httpx.AsyncClient(
                timeout=20, transport=self._transport
            ) as client:
                response = await client.get(
                    "https://openapi.naver.com/v1/search/news.json",
                    headers=headers,
                    params={"query": query, "display": limit, "sort": "date"},
                )
                response.raise_for_status()
                payload = response.json()
        except (httpx.HTTPError, ValueError) as error:
            raise LatestProviderError(
                self.name, "request_failed", f"Naver 뉴스 검색에 실패했습니다: {error}"
            ) from error
        articles: list[LatestArticle] = []
        for item in payload.get("items", []):
            url = str(item.get("originallink") or item.get("link") or "").strip()
            if not url:
                continue
            try:
                published_at = parsedate_to_datetime(str(item.get("pubDate") or ""))
            except (TypeError, ValueError):
                published_at = None
            articles.append(
                LatestArticle(
                    provider=self.name,
                    title=_clean_text(item.get("title")),
                    url=url,
                    description=_clean_text(item.get("description")),
                    published_at=published_at,
                    source_name="Naver News",
                    language=language or "ko",
                    # originallink가 곧 발행처 주소라 신뢰도 판정에 그대로 쓴다.
                    source_url=url,
                )
            )
        return articles


class NewsApiProvider:
    """NewsAPI everything 검색 결과를 공통 최신 문서로 정규화한다."""

    name = "newsapi"

    def __init__(
        self,
        api_key: str,
        *,
        transport: httpx.AsyncBaseTransport | None = None,
    ) -> None:
        """NewsAPI Key와 테스트용 HTTP Transport를 저장한다."""
        self._api_key = api_key
        self._transport = transport

    async def search(
        self, *, query: str, limit: int, language: str | None
    ) -> list[LatestArticle]:
        """NewsAPI 문서를 게시일 내림차순으로 검색한다."""
        params: dict[str, object] = {
            "q": query,
            "pageSize": limit,
            "sortBy": "publishedAt",
        }
        if language:
            params["language"] = language.split("-")[0]
        try:
            async with httpx.AsyncClient(
                timeout=20, transport=self._transport
            ) as client:
                response = await client.get(
                    "https://newsapi.org/v2/everything",
                    headers={"X-Api-Key": self._api_key},
                    params=params,
                )
                response.raise_for_status()
                payload = response.json()
        except (httpx.HTTPError, ValueError) as error:
            raise LatestProviderError(
                self.name, "request_failed", f"NewsAPI 검색에 실패했습니다: {error}"
            ) from error
        return [
            LatestArticle(
                provider=self.name,
                title=_clean_text(item.get("title")),
                url=str(item.get("url") or "").strip(),
                description=_clean_text(
                    item.get("description") or item.get("content")
                ),
                published_at=_iso_datetime(item.get("publishedAt")),
                source_name=_clean_text((item.get("source") or {}).get("name")),
                language=language,
            )
            for item in payload.get("articles", [])
            if str(item.get("url") or "").strip()
        ]


class GdeltNewsProvider:
    """GDELT DOC API의 기사 목록을 공통 최신 문서로 정규화한다."""

    name = "gdelt"

    def __init__(
        self,
        base_url: str = "https://api.gdeltproject.org",
        *,
        transport: httpx.AsyncBaseTransport | None = None,
    ) -> None:
        """GDELT 기본 URL과 테스트용 HTTP Transport를 저장한다."""
        self._base_url = base_url.rstrip("/")
        self._transport = transport

    async def search(
        self, *, query: str, limit: int, language: str | None
    ) -> list[LatestArticle]:
        """GDELT DOC API에서 최신 기사 목록을 검색한다."""
        params = {
            "query": query,
            "mode": "ArtList",
            "maxrecords": limit,
            "format": "json",
            "sort": "DateDesc",
        }
        try:
            async with httpx.AsyncClient(
                timeout=25, transport=self._transport
            ) as client:
                response = await client.get(
                    f"{self._base_url}/api/v2/doc/doc",
                    params=params,
                )
                response.raise_for_status()
                payload = response.json()
        except (httpx.HTTPError, ValueError) as error:
            raise LatestProviderError(
                self.name, "request_failed", f"GDELT 검색에 실패했습니다: {error}"
            ) from error
        return [
            LatestArticle(
                provider=self.name,
                title=_clean_text(item.get("title")),
                url=str(item.get("url") or "").strip(),
                description=_clean_text(
                    item.get("description") or item.get("snippet")
                ),
                published_at=_iso_datetime(
                    item.get("seendate") or item.get("date")
                ),
                source_name=_clean_text(item.get("domain")),
                language=_clean_text(item.get("language")) or language,
                source_url=(
                    f"https://{_clean_text(item.get('domain'))}"
                    if _clean_text(item.get("domain"))
                    else None
                ),
            )
            for item in payload.get("articles", [])
            if str(item.get("url") or "").strip()
        ]


class GoogleNewsRssProvider:
    """Google News RSS 검색 결과를 공통 최신 문서로 정규화한다.

    API Key 없이 동작하는 유일한 뉴스 Provider라, 자격 증명이 없는 환경
    (팀원 로컬 등)에서 기본 소스 역할을 한다. 기사 link는 Google 리다이렉트
    주소이므로 매체 정보는 source 요소에서 읽는다.
    """

    name = "google_news"

    def __init__(self, *, transport: httpx.AsyncBaseTransport | None = None) -> None:
        """테스트용 HTTP Transport를 저장한다."""
        self._transport = transport

    async def search(
        self, *, query: str, limit: int, language: str | None
    ) -> list[LatestArticle]:
        """Google News RSS 검색 피드에서 최신 기사 목록을 가져온다."""
        lang = (language or "ko").split("-")[0]
        country = "KR" if lang == "ko" else "US"
        params = {"q": query, "hl": lang, "gl": country, "ceid": f"{country}:{lang}"}
        try:
            async with httpx.AsyncClient(
                timeout=20, transport=self._transport, follow_redirects=True
            ) as client:
                response = await client.get(
                    "https://news.google.com/rss/search", params=params
                )
                response.raise_for_status()
                text = response.text
        except httpx.HTTPError as error:
            raise LatestProviderError(
                self.name,
                "request_failed",
                f"Google News RSS 조회에 실패했습니다: {error}",
            ) from error
        try:
            root = ElementTree.fromstring(text)
        except ElementTree.ParseError as error:
            raise LatestProviderError(
                self.name,
                "invalid_feed",
                f"Google News RSS 응답을 해석할 수 없습니다: {error}",
            ) from error
        articles: list[LatestArticle] = []
        for item in root.iter("item"):
            url = (item.findtext("link") or "").strip()
            if not url:
                continue
            try:
                published_at = parsedate_to_datetime(item.findtext("pubDate") or "")
            except (TypeError, ValueError):
                published_at = None
            source = item.find("source")
            source_name = _clean_text(source.text if source is not None else "")
            source_url = (source.get("url") or "").strip() if source is not None else ""
            articles.append(
                LatestArticle(
                    provider=self.name,
                    title=_clean_text(item.findtext("title")),
                    url=url,
                    description=_clean_text(item.findtext("description")),
                    published_at=published_at,
                    source_name=source_name or None,
                    language=lang,
                    # link는 Google 리다이렉트 주소라 발행처는 source 요소에서 읽는다.
                    source_url=source_url or None,
                )
            )
            if len(articles) >= limit:
                break
        return articles
