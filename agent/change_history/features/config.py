"""변경점 추적 에이전트의 실행 스위치와 모델 라우팅.

토글은 요청 단위(보고서 생성 API 플래그)로 켜지지만, 장애 시 서버에서 한 번에
끌 수 있는 환경변수 차단 스위치를 함께 둔다(critic·researcher와 같은 패턴).
"""

from __future__ import annotations

import os

_FALSY = {"0", "false", "no"}


def change_history_available() -> bool:
    """변경점 추적 경로를 서버에서 허용하는지 환경변수로 확인한다.

    끄면 요청이 토글을 켜서 보내도 기존 generate 경로로 처리한다. 요청 플래그가
    아니라 **운영 차단 스위치**다 — 델타 경로에 장애가 나도 리포트 발행 자체는
    멈추면 안 되기 때문이다. 기본값은 켬이다.
    """
    return os.getenv("CHANGE_HISTORY_ENABLED", "1").strip().lower() not in _FALSY


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
