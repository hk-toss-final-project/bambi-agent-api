"""변경점 추적 에이전트의 실행 스위치와 모델 라우팅.

토글은 요청 단위(보고서 생성 API 플래그)로 켜지지만, 장애 시 서버에서 한 번에
끌 수 있는 환경변수 차단 스위치를 함께 둔다(critic·researcher와 같은 패턴).
"""

from __future__ import annotations

import logging
import os
from datetime import UTC, date, datetime, timedelta, timezone, tzinfo
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

logger = logging.getLogger("agent.change_history.config")

_FALSY = {"0", "false", "no"}

# 델타 기준일의 기본 시간대. 저장소 전반은 UTC로 다루지만 **기준일만은 다르다** —
# 이 값은 타임라인의 절대 날짜("어제" → YYYY-MM-DD)로 사용자에게 그대로 보이므로,
# 읽는 사람의 달력과 같아야 한다. UTC로 재면 KST 00~09시에 만든 보고서의 날짜가
# 하루 밀린다(아침 브리핑 시간대가 정확히 여기에 걸린다).
#
# tzdata 없이도 정확하도록 고정 오프셋을 기본값으로 둔다. 한국은 1988년 이후
# 서머타임이 없어 UTC+9가 상시 정확하다. 다른 지역에 배포하면 환경변수로
# IANA 시간대 이름을 주면 된다.
_KST = timezone(timedelta(hours=9), "KST")


def change_history_available() -> bool:
    """변경점 추적 경로를 서버에서 허용하는지 환경변수로 확인한다.

    끄면 요청이 토글을 켜서 보내도 기존 generate 경로로 처리한다. 요청 플래그가
    아니라 **운영 차단 스위치**다 — 델타 경로에 장애가 나도 리포트 발행 자체는
    멈추면 안 되기 때문이다. 기본값은 켬이다.
    """
    return os.getenv("CHANGE_HISTORY_ENABLED", "1").strip().lower() not in _FALSY


def reference_timezone() -> tzinfo:
    """델타 기준일을 계산할 시간대를 환경변수에서 읽는다.

    환경변수가 없으면 서비스 기준 시간대(KST)를 쓴다. 이름이 잘못됐거나 배포
    환경에 tz 데이터가 없으면 경고만 남기고 기본값으로 되돌린다 — 여기서 UTC로
    떨어지면 고치려던 날짜 밀림이 조용히 되살아나기 때문이다.

    Returns:
        기준일 계산에 사용할 시간대
    """
    name = os.getenv("CHANGE_HISTORY_REFERENCE_TIMEZONE", "").strip()
    if not name:
        return _KST
    try:
        return ZoneInfo(name)
    except (ZoneInfoNotFoundError, ValueError):
        logger.warning(
            "CHANGE_HISTORY_REFERENCE_TIMEZONE=%s 를 해석하지 못해 KST로 진행합니다.",
            name,
        )
        return _KST


def current_reference_date(now: datetime | None = None) -> date:
    """델타 기준일(오늘)을 서비스 시간대로 계산한다.

    Args:
        now: 기준 시각. 생략하면 현재 UTC 시각을 쓴다(테스트가 "지금"에 흔들리지
            않도록 주입할 수 있게 열어 둔다).

    Returns:
        서비스 시간대에서 본 날짜
    """
    moment = now or datetime.now(UTC)
    if moment.tzinfo is None:
        moment = moment.replace(tzinfo=UTC)
    return moment.astimezone(reference_timezone()).date()


def impact_model(default_model: str) -> str:
    """파급효과 추론(Impact worker)에 쓸 모델을 정한다.

    Impact는 Overview·타임라인보다 추론 난이도가 확연히 높아, 이 노드만 더 강한
    모델로 올릴 수 있게 열어 둔다. 환경변수가 없으면 나머지와 같은 모델을 쓴다.

    Args:
        default_model: 그래프 실행에 사용 중인 기본 모델

    Returns:
        Impact worker가 사용할 모델 이름
    """
    return os.getenv("CHANGE_HISTORY_IMPACT_MODEL", "").strip() or default_model
