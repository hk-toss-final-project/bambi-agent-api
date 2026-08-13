"""기능 영역의 공개 facade.

구현 모듈의 기능 함수를 안정적인 import 경로로 다시 노출한다.
"""

from .features.rss import col_001
from .features.naver import col_002
from .features.gdelt import col_003
from .features.news_api import col_004
from .features.social import col_005
from .features.url import JinaReadError, JinaReadResult, extract_jina_image, find_article_body_offset, fetch_url_raw_via_jina, fetch_url_via_jina, is_probable_content_image_url, is_secure_content_image_url, parse_jina_reader_response, resolve_article_image
from .features.article_image import (
    ArticleImageFetchError,
    ArticleImageMetadata,
    extract_article_image_metadata,
    fetch_article_image_metadata,
)
from .features.latest import (
    GdeltNewsProvider,
    GoogleNewsRssProvider,
    LatestArticle,
    LatestInformationProvider,
    LatestProviderError,
    NaverNewsProvider,
    NewsApiProvider,
)
from .features.youtube import YouTubeSearchProvider, thumbnail_url
from .features.reddit import RedditSearchProvider

__all__ = [
    "GdeltNewsProvider",
    "GoogleNewsRssProvider",
    "ArticleImageFetchError",
    "ArticleImageMetadata",
    "JinaReadError",
    "JinaReadResult",
    "LatestArticle",
    "LatestInformationProvider",
    "LatestProviderError",
    "NaverNewsProvider",
    "NewsApiProvider",
    "RedditSearchProvider",
    "YouTubeSearchProvider",
    "extract_jina_image",
    "extract_article_image_metadata",
    "find_article_body_offset",
    "fetch_url_raw_via_jina",
    "fetch_url_via_jina",
    "fetch_article_image_metadata",
    "is_probable_content_image_url",
    "is_secure_content_image_url",
    "parse_jina_reader_response",
    "resolve_article_image",
    "thumbnail_url",
    "col_001",
    "col_002",
    "col_003",
    "col_004",
    "col_005",
]
