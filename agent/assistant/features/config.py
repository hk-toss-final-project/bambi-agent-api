"""키워드 비서(수집 범위·폴백·저장 경로)에 쓰는 설정값.

**선별 임계값은 여기 없다.** 유사도·스코어링·클러스터링·중복·발행 판정 값은
리포트 생성과 공유하는 공용 라이브러리가 단독으로 소유한다
([agent/selection/features/config.py](../../selection/features/config.py)).
값이 두 곳에 있으면 한쪽만 고쳐져 조용히 어긋나므로 소유자를 하나로 둔다.

여기 남는 것은 "선별 결과와 무관하거나, 비서 실행 방식에만 영향을 주는" 값이다:
수집 창, 기초 필터, 주간 트렌드 폴백 범위, JSON 폴백 저장 경로.

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

# 주간 트렌드 폴백에서 최근 며칠 수집분을 볼지.
WEEKLY_TREND_DAYS: int = _env_int("WEEKLY_TREND_DAYS", 7)

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
