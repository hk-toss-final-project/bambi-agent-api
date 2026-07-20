"""수집·스코어링·중복 제거·보고서 판정에 쓰는 모든 설정값.

명세의 상수(COLLECT_WINDOW_DAYS, LAMBDA_*, MIN_SIMILARITY, DUP_THRESHOLD,
DEDUP_LOOKBACK_DAYS, PUBLISH_THRESHOLD, MAX_DAILY_ITEMS, 소스 가중치 테이블)를
이 파일 하나에 모아, 임계값 튜닝 시 코드 곳곳을 뒤지지 않게 한다.

모든 값은 같은 이름의 환경변수로 오버라이드할 수 있다(예: `COLLECT_WINDOW_DAYS=5`).
환경변수가 없거나 형식이 잘못되면 기본값을 쓴다.
"""

from __future__ import annotations

import os
from pathlib import Path


def _env_int(name: str, default: int) -> int:
    """환경변수를 정수로 읽는다. 없거나 형식이 잘못되면 기본값을 반환한다."""
    try:
        return int(os.environ[name])
    except (KeyError, ValueError):
        return default


def _env_float(name: str, default: float) -> float:
    """환경변수를 실수로 읽는다. 없거나 형식이 잘못되면 기본값을 반환한다."""
    try:
        return float(os.environ[name])
    except (KeyError, ValueError):
        return default


# ── 1. 수집 범위 ──────────────────────────────────────────────────────────
# 매일 실행 시 최근 며칠치 문서만 수집할지.
COLLECT_WINDOW_DAYS: int = _env_int("COLLECT_WINDOW_DAYS", 3)

# 기초 필터: 임베딩 입력으로 쓸 텍스트(제목+요지)가 이보다 짧으면 스팸/빈 글로 본다.
MIN_DOC_CHARS: int = _env_int("MIN_DOC_CHARS", 15)

# ── 3. 스코어링 ──────────────────────────────────────────────────────────
# 토픽 임베딩과의 코사인 유사도 최소 기준. 미달 시 즉시 제외.
MIN_SIMILARITY: float = _env_float("MIN_SIMILARITY", 0.6)

# freshness = exp(-λ × 경과일수). 콘텐츠 타입별 감쇠 상수.
LAMBDA_NEWS: float = _env_float("LAMBDA_NEWS", 0.5)        # 뉴스/릴리스: 약 1.4일 반감
LAMBDA_EVERGREEN: float = _env_float("LAMBDA_EVERGREEN", 0.05)  # 개념/튜토리얼: 거의 감쇠 없음

# 콜드 스타트(해당 사용자·키워드의 첫 수집) 또는 날짜 미상 문서의 신선도 중립값.
COLD_START_FRESHNESS: float = _env_float("COLD_START_FRESHNESS", 0.5)

# 미등록 소스의 기본 가중치.
DEFAULT_SOURCE_WEIGHT: float = _env_float("DEFAULT_SOURCE_WEIGHT", 0.5)

# 소스 신뢰도 가중치 테이블 (도메인 → 가중치).
# 기존 수집 소스(Google News 경유 언론사, YouTube, Reddit)를 기준으로 작성했다.
#   1.0 공식 발표/원문(공식 블로그, 릴리스 노트)
#   0.8 주요 언론/전문 매체
#   0.6 개인 블로그/커뮤니티
# URL 도메인의 접미사 일치로 조회하므로 서브도메인(news.example.com)도 매칭된다.
SOURCE_WEIGHTS: dict[str, float] = {
    # 공식 발표/원문
    "openai.com": 1.0,
    "anthropic.com": 1.0,
    "blog.google": 1.0,
    "microsoft.com": 1.0,
    "apple.com": 1.0,
    "nvidia.com": 1.0,
    "samsung.com": 1.0,
    "github.com": 1.0,
    "krx.co.kr": 1.0,
    "fss.or.kr": 1.0,
    "bok.or.kr": 1.0,
    # 주요 언론/전문 매체
    "yna.co.kr": 0.8,
    "yonhapnewstv.co.kr": 0.8,
    "chosun.com": 0.8,
    "joongang.co.kr": 0.8,
    "donga.com": 0.8,
    "hani.co.kr": 0.8,
    "khan.co.kr": 0.8,
    "mk.co.kr": 0.8,
    "hankyung.com": 0.8,
    "sedaily.com": 0.8,
    "edaily.co.kr": 0.8,
    "mt.co.kr": 0.8,
    "etnews.com": 0.8,
    "zdnet.co.kr": 0.8,
    "bloter.net": 0.8,
    "reuters.com": 0.8,
    "bloomberg.com": 0.8,
    "wsj.com": 0.8,
    "ft.com": 0.8,
    "techcrunch.com": 0.8,
    "theverge.com": 0.8,
    "arstechnica.com": 0.8,
    # 개인 블로그/커뮤니티
    "reddit.com": 0.6,
    "youtube.com": 0.6,
    "youtu.be": 0.6,
    "medium.com": 0.6,
    "tistory.com": 0.6,
    "velog.io": 0.6,
    "brunch.co.kr": 0.6,
}

# ── 4. 클러스터링 ────────────────────────────────────────────────────────
# 같은 클러스터로 묶는 코사인 유사도 기준.
CLUSTER_SIM_THRESHOLD: float = _env_float("CLUSTER_SIM_THRESHOLD", 0.8)

# cluster_boost = 1 + 0.1 × (클러스터 크기 - 1), 상한.
CLUSTER_BOOST_CAP: float = _env_float("CLUSTER_BOOST_CAP", 1.5)

# ── 5. 중복 제거 ─────────────────────────────────────────────────────────
# 최근 며칠간의 보고서 아이템 임베딩을 중복 검사에 쓸지.
DEDUP_LOOKBACK_DAYS: int = _env_int("DEDUP_LOOKBACK_DAYS", 7)

# 이 유사도 이상이면 "이미 다룬 소식"으로 본다.
DUP_THRESHOLD: float = _env_float("DUP_THRESHOLD", 0.85)

# 이 유사도 이상이면 후속 업데이트가 아니라 사실상 같은 문서로 본다.
# DUP_THRESHOLD ≤ 유사도 < DUP_STRICT_THRESHOLD 이고 기존 보고 이후 발행된 문서면
# "업데이트"로 표시하고 포함할 수 있다.
DUP_STRICT_THRESHOLD: float = _env_float("DUP_STRICT_THRESHOLD", 0.95)

# ── 6. 보고서 판정 ───────────────────────────────────────────────────────
# 당일 신규 아이템으로 채택할 최소 final_score.
PUBLISH_THRESHOLD: float = _env_float("PUBLISH_THRESHOLD", 0.5)

# 하루 보고서에 싣는 최대 아이템 수.
MAX_DAILY_ITEMS: int = _env_int("MAX_DAILY_ITEMS", 5)

# 주간 트렌드 폴백에서 최근 며칠 수집분을 볼지.
WEEKLY_TREND_DAYS: int = _env_int("WEEKLY_TREND_DAYS", 7)

# ── 임베딩 ───────────────────────────────────────────────────────────────
# OpenAI 임베딩 모델 이름 (langchain-openai 경유).
EMBEDDING_MODEL: str = os.environ.get("EMBEDDING_MODEL", "text-embedding-3-small")

# ── 저장 경로 ────────────────────────────────────────────────────────────
# 이력 파일(수집·보고·시청·기사)을 저장할 디렉터리. 기본값은 저장소 루트의 data/
# 이며(agent/assistant/ 기준 2단계 위), ASSISTANT_DATA_DIR 환경변수로 옮길 수 있다.
# history·dedup 두 모듈이 이 값을 공유해, 경로 계산을 한 곳에만 둔다.
DATA_DIR: Path = Path(
    os.environ.get("ASSISTANT_DATA_DIR") or Path(__file__).resolve().parents[2] / "data"
)


def collect_window_hours() -> float:
    """수집 창을 시간 단위로 반환한다 (COLLECT_WINDOW_DAYS × 24)."""
    return COLLECT_WINDOW_DAYS * 24.0


def source_weight_for_domain(domain: str) -> float:
    """도메인의 소스 가중치를 찾는다. 서브도메인은 접미사 일치로 매칭한다.

    등록되지 않은 도메인은 DEFAULT_SOURCE_WEIGHT를 반환한다.
    """
    normalized = domain.strip().lower().removeprefix("www.")
    if not normalized:
        return DEFAULT_SOURCE_WEIGHT
    for registered, weight in SOURCE_WEIGHTS.items():
        if normalized == registered or normalized.endswith("." + registered):
            return weight
    return DEFAULT_SOURCE_WEIGHT
