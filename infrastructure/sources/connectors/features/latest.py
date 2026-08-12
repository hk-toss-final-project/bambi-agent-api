"""Naver·NewsAPI·GDELT·Google News RSS 최신 정보 검색 Connector.

서로 다른 외부 뉴스 API 응답을 제목, URL, 게시 시각, 설명과 Provider를 갖는
공통 LatestArticle 모델로 정규화한다.
"""

import asyncio
import html
import logging
import os
import re
import threading
import time
from dataclasses import dataclass
from datetime import UTC, datetime
from email.utils import parsedate_to_datetime
from collections.abc import Callable
from typing import Protocol
from xml.etree import ElementTree

import httpx

logger = logging.getLogger("infrastructure.sources.connectors.latest")

_HTML_TAG = re.compile(r"<[^>]+>")


def _env_float(name: str, default: float) -> float:
    """환경변수를 실수로 읽는다. 없거나 형식이 잘못되면 기본값을 반환한다."""
    try:
        return float(os.environ[name])
    except (KeyError, ValueError):
        return default


# ── GDELT 호출 간격 제어 ────────────────────────────────────────────────────
# GDELT는 인증 없는 공개 API라 호출 빈도를 스스로 제한한다. 429 본문이 조건을
# 직접 알려준다: "Please limit requests to one every 5 seconds".
#
# 2026-08-10 실측:
#
#   ① **한 번 걸리면 오래 간다.** 5초·30초·60초·120초·240초 뒤 재호출이 전부
#      429였다. 다음 호출을 기다리는 것으로는 풀리지 않는다.
#   ② 응답은 성공이든 429든 10~17초가 걸린다.
#
# 그래서 대응이 두 겹이다. 평소에는 최소 간격을 지켜 429를 만들지 않고, 그래도
# 걸리면 쿨다운 동안 호출을 건너뛴다. Provider 실패 격리가 이미 있어 건너뛰어도
# naver·google_news 수집은 그대로 완료된다.
#
# ⚠️ **이 제어는 수집을 빠르게 하지 않는다. 속도를 기대하고 손대지 마라.**
# 같은 조건에서 쿨다운만 켜고 끄며 두 번씩 재보니 차이가 없었다
# (OFF 94.7초 vs ON 94.6초, 검색어 3개 기준). GDELT는 뉴스 소스 안에서
# naver·google_news와 **동시에** 호출되므로(feeds.fetch_provider_entries),
# 10초를 쓰든 건너뛰든 28초짜리 다른 Provider 뒤에 가려 임계 경로가 아니다
# (격리 실측: 전체 32.8초 / gdelt 제외 28.9초 / gdelt만 10.2초).
#
# 그럼에도 두는 이유는 셋이다. (a) 공개 API가 명시한 조건을 지키는 것,
# (b) 한 번 걸리면 몇 분간 GDELT 자료를 통째로 잃으므로 애초에 안 걸리는 편이
# 낫다는 것, (c) 429를 request_failed가 아니라 rate_limited로 구분해 로그에서
# "외부 장애"와 "우리가 너무 자주 불렀음"이 섞이지 않게 하는 것이다.
#
# 상태는 프로세스 전역이다. Provider 객체가 호출마다 새로 만들어지고
# (_build_provider), 수집이 스레드로 나뉘어 돌기 때문이다(pipeline.collect_documents).
# 여러 Worker 프로세스가 같은 IP를 쓰면 이 제어만으로는 부족하다.
GDELT_MIN_INTERVAL_SECONDS: float = _env_float("GDELT_MIN_INTERVAL_SECONDS", 5.0)
GDELT_COOLDOWN_SECONDS: float = _env_float("GDELT_COOLDOWN_SECONDS", 300.0)

_gdelt_lock = threading.Lock()
_gdelt_next_call_at: float = 0.0
_gdelt_cooldown_until: float = 0.0

# Google News RSS 기사 URL 디코더가 429 또는 /sorry/index를 반환하면 같은 공인
# IP의 후속 요청도 계속 차단된다. 차단을 감지한 프로세스는 일정 시간 디코딩을
# 시도하지 않아 Google과 Worker Lease를 함께 보호한다.
GOOGLE_NEWS_COOLDOWN_SECONDS: float = _env_float(
    "GOOGLE_NEWS_COOLDOWN_SECONDS", 900.0
)
_google_news_lock = threading.Lock()
_google_news_cooldown_until: float = 0.0


def reset_gdelt_rate_limit_state() -> None:
    """GDELT 호출 간격·쿨다운 상태를 초기화한다 (테스트 격리용)."""
    global _gdelt_next_call_at, _gdelt_cooldown_until
    with _gdelt_lock:
        _gdelt_next_call_at = 0.0
        _gdelt_cooldown_until = 0.0


def reset_google_news_rate_limit_state() -> None:
    """Google News 디코딩 쿨다운 상태를 초기화한다 (테스트 격리용)."""
    global _google_news_cooldown_until
    with _google_news_lock:
        _google_news_cooldown_until = 0.0


def _google_news_cooldown_active() -> bool:
    """Google News 디코딩 쿨다운이 진행 중인지 반환한다."""
    with _google_news_lock:
        return time.monotonic() < _google_news_cooldown_until


def _start_google_news_cooldown() -> None:
    """Google 봇 차단을 감지한 시점부터 디코딩 쿨다운을 건다."""
    global _google_news_cooldown_until
    with _google_news_lock:
        _google_news_cooldown_until = (
            time.monotonic() + GOOGLE_NEWS_COOLDOWN_SECONDS
        )


def _is_google_news_rate_limit(value: object) -> bool:
    """외부 디코더 메시지가 Google의 호출 제한·봇 차단인지 판별한다."""
    message = str(value or "").casefold()
    return any(
        marker in message
        for marker in (
            "429",
            "too many requests",
            "google.com/sorry",
            "/sorry/index",
        )
    )


def _google_news_rate_limit_error() -> "LatestProviderError":
    """내부 차단 URL을 노출하지 않는 Google News 호출 제한 오류를 만든다."""
    return LatestProviderError(
        "google_news",
        "rate_limited",
        "Google News 기사 URL 디코딩이 일시적으로 차단됐습니다.",
    )


def _reserve_gdelt_slot() -> float:
    """다음 GDELT 호출 자리를 잡고 대기할 시간(초)을 돌려준다.

    쿨다운 중이면 호출하지 않는다는 뜻으로 -1.0을 돌려준다. 자리를 잡는 즉시
    다음 호출 가능 시각을 밀어 두므로, 여러 스레드가 동시에 들어와도 실제
    호출은 최소 간격만큼 벌어진다.

    Returns:
        대기할 초. 쿨다운 중이면 -1.0.
    """
    global _gdelt_next_call_at
    now = time.monotonic()
    with _gdelt_lock:
        if now < _gdelt_cooldown_until:
            return -1.0
        wait = max(0.0, _gdelt_next_call_at - now)
        _gdelt_next_call_at = now + wait + GDELT_MIN_INTERVAL_SECONDS
        return wait


def _start_gdelt_cooldown() -> None:
    """429를 받은 시점부터 쿨다운을 건다."""
    global _gdelt_cooldown_until
    with _gdelt_lock:
        _gdelt_cooldown_until = time.monotonic() + GDELT_COOLDOWN_SECONDS


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
    image_url: str | None = None


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
        """Naver 뉴스를 최신순·관련도순 양쪽으로 조회해 합친 결과를 반환한다.

        정렬 하나만 쓰면 둘 중 하나를 잃는다(2026-07-28 실측).

            sort=date   신선하지만 부정확 — 'Cloudflare' 검색에 "Morgan Stanley
                        Downgrades Adobe" 같은 무관 기사가 올라온다(관련 3/10).
            sort=sim    정확하지만 낡았다 — 같은 검색어에서 관련 9/10이지만 평균
                        190일 전 기사였다.

        어느 쪽을 고르든 손해라, 양쪽을 모두 받아 URL로 중복을 제거한다. 최종
        순위는 수집기가 정하지 않는다 — agent/selection이 유사도 x 신선도로
        판정하므로, 낡았지만 정확한 기사와 신선하지만 무관한 기사가 각각 제
        축에서 감점된다. 수집 단계는 후보를 넓게 확보하는 데만 집중한다.
        """
        payloads = []
        for sort in ("date", "sim"):
            payloads.append(await self._fetch(query, limit=limit, sort=sort))

        articles: list[LatestArticle] = []
        seen_urls: set[str] = set()
        for payload in payloads:
            articles.extend(
                self._to_articles(payload, language=language, seen_urls=seen_urls)
            )
        return articles

    async def _fetch(self, query: str, *, limit: int, sort: str) -> dict:
        """지정한 정렬로 Naver 뉴스 검색 API를 호출한다."""
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
                    params={"query": query, "display": limit, "sort": sort},
                )
                response.raise_for_status()
                return response.json()
        except (httpx.HTTPError, ValueError) as error:
            raise LatestProviderError(
                self.name, "request_failed", f"Naver 뉴스 검색에 실패했습니다: {error}"
            ) from error

    def _to_articles(
        self, payload: dict, *, language: str | None, seen_urls: set[str]
    ) -> list[LatestArticle]:
        """Naver 응답을 공통 문서로 변환한다. 이미 본 URL은 건너뛴다."""
        articles: list[LatestArticle] = []
        for item in payload.get("items", []):
            url = str(item.get("originallink") or item.get("link") or "").strip()
            # 두 정렬이 같은 기사를 함께 반환하는 일이 흔하므로 URL로 걸러낸다.
            if not url or url in seen_urls:
                continue
            seen_urls.add(url)
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
                image_url=str(item.get("urlToImage") or "").strip() or None,
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
        """GDELT DOC API에서 최신 기사 목록을 검색한다.

        호출 전에 프로세스 전역 간격 제어를 통과해야 한다(GDELT_MIN_INTERVAL_SECONDS
        주석 참고). 429를 받으면 쿨다운을 걸어, 어차피 실패할 뒤이은 호출이 12초씩
        낭비하지 않게 한다.

        Raises:
            LatestProviderError: 쿨다운 중(`rate_limited`)이거나 요청이 실패했을 때
        """
        wait = _reserve_gdelt_slot()
        if wait < 0:
            raise LatestProviderError(
                self.name,
                "rate_limited",
                "GDELT 호출 제한(429) 쿨다운 중이라 이번 수집은 건너뜁니다.",
            )
        if wait > 0:
            await asyncio.sleep(wait)
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
                # 429는 다른 실패와 다르게 다룬다. 재시도해도 몇 분간 계속
                # 429이므로(실측) 쿨다운을 걸어 호출 자체를 멈춘다.
                if response.status_code == 429:
                    _start_gdelt_cooldown()
                    logger.warning(
                        "GDELT 호출 제한(429). %.0f초 동안 GDELT 수집을 건너뜁니다.",
                        GDELT_COOLDOWN_SECONDS,
                    )
                    raise LatestProviderError(
                        self.name,
                        "rate_limited",
                        "GDELT 호출 제한(429)에 걸려 이번 수집을 건너뜁니다.",
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
                image_url=str(item.get("socialimage") or "").strip() or None,
            )
            for item in payload.get("articles", [])
            if str(item.get("url") or "").strip()
        ]


def decode_google_news_url(url: str) -> str:
    """Google News 리다이렉트 URL을 원본 기사 주소로 푼다. 실패하면 빈 문자열.

    RSS의 기사 link는 `news.google.com/rss/articles/CBMi…` 형태의 암호화된
    중계 주소다. 이 상태로는 본문을 확보할 수 없다 — Jina Reader가 403을
    반환하고(2026-07-28 실측 111건 전원 실패), 리다이렉트는 HTTP로 풀리지
    않는다(JS 이동이라 follow_redirects도 news.google.com에 머문다).

    googlenewsdecoder는 Google 내부 엔드포인트를 호출해 원본을 복원한다.
    실측(2026-07-28): 31건 전원 성공, URL당 약 1.2초, 25건 연속 호출에도 429 없음.

    Google이 방식을 바꾸면 깨질 수 있으므로 실패를 정상 경로로 다룬다. 호출자는
    빈 문자열을 받으면 그 기사를 **수집에서 제외**해야 한다 — 본문 없는 문서를
    풀에 남기면 제목만 반복돼 검색 점수만 높은 잡음이 된다.

    Args:
        url: Google News RSS의 기사 link

    Returns:
        원본 기사 URL. 디코딩 실패 시 빈 문자열.
    """
    if "news.google.com" not in url:
        return url
    if _google_news_cooldown_active():
        raise _google_news_rate_limit_error()
    try:
        from googlenewsdecoder import gnewsdecoder

        result = gnewsdecoder(url)
    except Exception as error:  # noqa: BLE001 — 외부 서비스 의존, 실패는 제외로 처리
        if _is_google_news_rate_limit(error):
            _start_google_news_cooldown()
            raise _google_news_rate_limit_error() from error
        logger.info("Google News URL 디코딩 실패: %s", error)
        return ""
    if not result.get("status"):
        message = result.get("message")
        if _is_google_news_rate_limit(message):
            _start_google_news_cooldown()
            raise _google_news_rate_limit_error()
        logger.info("Google News URL 디코딩 실패: %s", message)
        return ""
    decoded = str(result.get("decoded_url") or "").strip()
    return decoded if decoded and "news.google.com" not in decoded else ""


class GoogleNewsRssProvider:
    """Google News RSS 검색 결과를 공통 최신 문서로 정규화한다.

    API Key 없이 동작하는 유일한 뉴스 Provider라, 자격 증명이 없는 환경
    (팀원 로컬 등)에서 기본 소스 역할을 한다.

    기사 link는 Google 리다이렉트 주소라 그대로 저장하면 본문을 확보할 수 없다.
    수집 시점에 원본 주소로 디코딩하고, 실패한 기사는 결과에서 제외한다
    (decode_google_news_url 참고).
    """

    name = "google_news"

    def __init__(
        self,
        *,
        transport: httpx.AsyncBaseTransport | None = None,
        url_decoder: Callable[[str], str] | None = None,
    ) -> None:
        """테스트용 HTTP Transport와 URL 디코더를 저장한다.

        url_decoder를 주입할 수 있게 둔 이유는 테스트가 Google 내부 엔드포인트를
        호출하지 않게 하기 위해서다(단위 테스트는 네트워크 없이 결정적으로 돌아야
        한다). 생략하면 실제 디코더를 쓴다.
        """
        self._transport = transport
        self._decode = url_decoder or decode_google_news_url

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
        skipped = 0
        for item in root.iter("item"):
            link = (item.findtext("link") or "").strip()
            if not link:
                continue
            # 리다이렉트 주소를 원본 기사 URL로 푼다. 실패하면 그 기사는 버린다 —
            # 본문을 확보할 수 없어 풀에 제목만 남는 잡음이 되기 때문이다.
            url = self._decode(link)
            if not url:
                skipped += 1
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
                    # 디코딩된 기사 URL이 곧 발행처 주소다. source 요소의 url은
                    # 언론사 홈페이지라 기사를 가리키지 않으므로 폴백으로만 쓴다.
                    source_url=url or source_url or None,
                )
            )
            if len(articles) >= limit:
                break
        if skipped:
            logger.info(
                "Google News 디코딩 실패로 %d건 제외 (수집 %d건)", skipped, len(articles)
            )
        return articles
