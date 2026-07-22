"""수집·스코어링·중복 제거·보고서 판정에 쓰는 모든 설정값.

명세의 상수(COLLECT_WINDOW_DAYS, LAMBDA_*, SIMILARITY_*, DUP_THRESHOLD,
DEDUP_LOOKBACK_DAYS, PUBLISH_*, MAX_DAILY_ITEMS, 소스 가중치 테이블)를
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
# 토픽 임베딩과의 코사인 유사도 하한. 절대값이 아니라 "절대 하한 + 상대 비율"의
# 하이브리드를 쓴다.
#
#   cutoff = max(SIMILARITY_FLOOR, 이번 실행 최고 유사도 × SIMILARITY_RATIO)
#
# 고정 임계값을 쓰지 않는 이유: 짧은 키워드와 긴 문서의 코사인 유사도는 0.3~0.5대에
# 형성되고, 그 분포가 키워드마다 크게 다르다. 실측(text-embedding-3-small)에서
# '코스피'는 최고 0.475, '인공지능 반도체 수출 규제'는 최고 0.412였다. 키워드가
# 길고 구체적일수록 임베딩이 분산돼 유사도 절댓값이 내려가므로, 고정값 하나로는
# 어떤 키워드는 다 통과시키고 어떤 키워드는 전멸시킨다(0.40 기준 실측: 코스피
# 16건 vs 커피 1건). 상대 비율이 이 스케일 차이를 흡수한다.
#
# SIMILARITY_FLOOR는 수집 결과가 통째로 무관한 경우(최고 유사도 자체가 낮은 경우)
# 쓰레기를 통과시키지 않기 위한 안전장치다.
SIMILARITY_FLOOR: float = _env_float("SIMILARITY_FLOOR", 0.25)
SIMILARITY_RATIO: float = _env_float("SIMILARITY_RATIO", 0.75)

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
# 같은 사건을 다룬 문서로 보고 하나로 묶는 코사인 유사도 기준.
#
# 유사도 컷과 달리 절대값을 쓴다. "이 둘이 같은 사건인가"는 키워드와 무관한
# 판단이고, 문서 대 문서(둘 다 긴 글) 비교라 키워드 대 문서처럼 스케일이
# 흔들리지 않기 때문이다.
#
# 실측('코스피' 뉴스 26건, 문서쌍 325개): 최대 0.737 / 중앙 0.433. 같은 사건을
# 다룬 기사쌍은 0.68~0.74에 몰렸고, 0.60 아래로 내리면 서로 다른 이슈가 섞였다.
# 이전 기본값 0.8은 실측 최댓값(0.737)보다 높아 어떤 문서도 병합되지 않았다
# (26건 → 26개 클러스터, 전부 크기 1). 같은 사건 기사가 각각 별개 아이템으로
# 보고서에 중복 노출되던 원인이다.
CLUSTER_SIM_THRESHOLD: float = _env_float("CLUSTER_SIM_THRESHOLD", 0.65)

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
# 당일 신규 아이템으로 채택할 final_score 하한. 유사도와 같은 이유로 상대 기준을
# 쓴다 — final_score는 similarity를 곱해서 만들므로 유사도 스케일 문제를 그대로
# 물려받는다(실측 '코스피' 이론상 최대 0.357로, 고정값 0.5에는 도달할 수 없었다).
#
#   cutoff = max(PUBLISH_FLOOR, 이번 실행 최고 final_score × PUBLISH_RATIO)
PUBLISH_FLOOR: float = _env_float("PUBLISH_FLOOR", 0.05)
PUBLISH_RATIO: float = _env_float("PUBLISH_RATIO", 0.5)

# 하루 보고서에 싣는 최대 아이템 수.
MAX_DAILY_ITEMS: int = _env_int("MAX_DAILY_ITEMS", 5)

# 주간 트렌드 폴백에서 최근 며칠 수집분을 볼지.
WEEKLY_TREND_DAYS: int = _env_int("WEEKLY_TREND_DAYS", 7)

# ── 임베딩 ───────────────────────────────────────────────────────────────
# OpenAI 임베딩 모델 이름 (langchain-openai 경유).
EMBEDDING_MODEL: str = os.environ.get("EMBEDDING_MODEL", "text-embedding-3-small")

# ── 저장 경로 ────────────────────────────────────────────────────────────
# 이력 파일(수집·보고·시청·기사)을 저장할 디렉터리. PostgreSQL을 쓸 수 없을 때의
# 폴백 경로다(저장소 선택은 storage.py 참고). ASSISTANT_DATA_DIR 환경변수로 옮길 수 있다.
#
# 경로는 이 파일 위치를 기준으로 저장소 루트를 거슬러 올라간다:
#   agent/assistant/features/config.py → parents[0]=features, [1]=assistant, [2]=agent, [3]=루트
# facade 마이그레이션으로 이 파일이 features/ 아래로 내려가면서 한 단계가 밀려
# 한동안 agent/data/를 가리켰고, 그 결과 이력이 data/와 agent/data/ 두 곳으로
# 쪼개졌다. 파일이 다시 이동하면 같은 문제가 생기므로 아래 테스트로 고정한다
# (tests/agent/assistant/test_storage.py::test_data_dir_points_to_repository_root).
_REPOSITORY_ROOT = Path(__file__).resolve().parents[3]
DATA_DIR: Path = Path(
    os.environ.get("ASSISTANT_DATA_DIR") or _REPOSITORY_ROOT / "data"
)


def collect_window_days() -> int:
    """수집 창 일수를 반환한다.

    상수를 직접 import하면 환경변수 오버라이드 후 모듈을 reload해도 호출자 쪽
    값이 갱신되지 않으므로, 외부에는 이 함수로 노출한다.
    """
    return COLLECT_WINDOW_DAYS


def collect_window_hours() -> float:
    """수집 창을 시간 단위로 반환한다 (COLLECT_WINDOW_DAYS × 24)."""
    return COLLECT_WINDOW_DAYS * 24.0


def similarity_cutoff(best_similarity: float) -> float:
    """이번 실행의 유사도 컷을 계산한다 (절대 하한과 상대 비율 중 큰 값).

    Args:
        best_similarity: 이번 실행에서 관측된 최고 코사인 유사도

    Returns:
        이 값 미만인 문서는 제외한다.
    """
    return max(SIMILARITY_FLOOR, best_similarity * SIMILARITY_RATIO)


def publish_cutoff(best_score: float) -> float:
    """이번 실행의 발행 컷을 계산한다 (절대 하한과 상대 비율 중 큰 값).

    Args:
        best_score: 이번 실행에서 관측된 최고 final_score

    Returns:
        이 값 미만인 클러스터는 보고서에 싣지 않는다.
    """
    return max(PUBLISH_FLOOR, best_score * PUBLISH_RATIO)


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
