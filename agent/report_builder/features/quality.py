"""생성된 리포트의 품질을 코드로 판정한다 (LLM 호출 없음, 무료·결정적).

리포트를 한 번 생성하고 무조건 내보내면, 근거를 하나도 인용하지 않았거나 본문이
지나치게 짧은 실패도 그대로 사용자에게 나간다. 이 모듈은 LLM에게 묻지 않고도 알 수
있는 명백한 실패를 걸러, 재생성이 필요한지 판정한다.

설계 원칙은 키워드 비서의 outcomes.py와 같다 — "다시 써서 나아질 수 있는 문제일
때만" 재생성을 허용한다. 근거가 애초에 부족했던 것은 검색 문제라 재생성해도 없는
근거가 생기지 않으므로 재생성 대상에서 뺀다.

두 단계 판정 중 여기는 1단계(무료 코드 검사)만 담당한다. 2단계(LLM 의미 판정:
주제 적합성·근거 뒷받침)는 비용이 들어 별도 모듈로 뒤에 붙인다.
"""

from __future__ import annotations

import os
import re
from dataclasses import dataclass

from shared.report_models import GeneratedReportContent

# 본문 속 인용 표기 [P1]/[G2]/[L3] 를 센다. P=개인 Wiki, G=Global, L=실시간.
# generation.py의 _CITATION_REF와 같은 형식이며, 함께 유지해야 한다.
_CITATION_REF = re.compile(r"\[([PGL]\d+)\]")


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


# ── 판정 기준값 (실측 후 튜닝 대상) ────────────────────────────────────────
# 본문이 이보다 짧으면 내용이 부실하다고 본다.
MIN_BODY_CHARS: int = _env_int("REPORT_MIN_BODY_CHARS", 300)

# 제공한 근거 중 실제 인용한 비율이 이보다 낮으면 "자료를 안 썼다"고 본다.
# 근거를 많이 줬는데 한두 개만 인용하면 생성이 자료를 활용하지 않은 것이다.
MIN_CITATION_COVERAGE: float = _env_float("REPORT_MIN_CITATION_COVERAGE", 0.3)


# ── 판정 결과 코드 ─────────────────────────────────────────────────────────
PASS = "pass"
NO_CITATIONS = "no_citations"
TOO_SHORT = "too_short"
IGNORES_CONTEXT = "ignores_context"

# 재생성해서 나아질 수 있는 판정. (PASS는 통과라 재생성 안 함)
# 셋 다 "생성이 자료를 제대로 안 썼다"는 문제라, 교정 지시를 주고 다시 쓰면 나아질 수
# 있다. 근거 부족(검색 문제)은 여기 없다 — 그건 재생성 대상이 아니다.
REGENERATABLE = frozenset({NO_CITATIONS, TOO_SHORT, IGNORES_CONTEXT})

# 사람이 읽는 판정 설명. 재생성 시 LLM에게 주는 교정 지시로도 쓴다.
_DESCRIPTIONS = {
    PASS: "품질 기준을 통과했습니다.",
    NO_CITATIONS: "본문이 근거를 하나도 인용하지 않았습니다.",
    TOO_SHORT: f"본문이 최소 길이({MIN_BODY_CHARS}자)에 못 미칩니다.",
    IGNORES_CONTEXT: "제공한 근거를 거의 인용하지 않았습니다.",
}

# 재생성 시 프롬프트에 덧붙일 교정 지시. 같은 근거·프롬프트로 다시 쓰면 결과가
# 같으므로, "무엇이 문제였는지"를 알려줘야 2차가 1차보다 나아진다.
_CORRECTIONS = {
    NO_CITATIONS: "이전 생성은 근거를 하나도 인용하지 않았습니다. 본문의 각 핵심 주장에 "
    "반드시 [P1]·[G2]·[L3] 형식으로 근거를 인용하세요.",
    TOO_SHORT: f"이전 생성은 본문이 너무 짧았습니다. 근거를 더 활용해 최소 {MIN_BODY_CHARS}자 "
    "이상으로 충실히 작성하세요.",
    IGNORES_CONTEXT: "이전 생성은 제공한 근거 대부분을 쓰지 않았습니다. 관련 있는 근거를 "
    "더 폭넓게 인용해 반영하세요.",
}


@dataclass(frozen=True, slots=True)
class QualityVerdict:
    """리포트 품질 판정 결과.

    Attributes:
        outcome: 판정 코드 (PASS 또는 재생성 대상 코드)
        should_regenerate: 재생성이 필요한지
        reason: 사람이 읽는 판정 설명 (trace·로그용)
        correction: 재생성 시 프롬프트에 덧붙일 교정 지시 (통과면 빈 문자열)
    """

    outcome: str
    should_regenerate: bool
    reason: str
    correction: str


def evaluate_report(
    content: GeneratedReportContent,
    *,
    context_count: int,
) -> QualityVerdict:
    """생성된 리포트를 코드로 점검해 재생성 필요 여부를 판정한다.

    LLM을 호출하지 않는다. 명백한 실패를 위에서부터 순서대로 검사하고, 첫 번째로
    걸린 판정을 반환한다(하나라도 걸리면 재생성 대상이므로 나머지는 볼 필요 없다).

    Args:
        content: 생성된 리포트 (title·summary·body·citation_references)
        context_count: 생성에 실제로 넣은 근거 문서 수. 인용률 계산의 분모다.

    Returns:
        QualityVerdict. outcome이 PASS면 그대로 발행, 아니면 correction을 붙여 재생성.
    """
    body = content.body or ""
    cited = {ref for ref in _CITATION_REF.findall(body)}

    # 1. 인용 0개 — 근거 없이 쓴 글.
    if not cited and not content.citation_references:
        return _verdict(NO_CITATIONS)

    # 2. 본문이 너무 짧음.
    if len(body.strip()) < MIN_BODY_CHARS:
        return _verdict(TOO_SHORT)

    # 3. 근거를 거의 안 씀 (근거를 줬는데 인용률이 하한 미만).
    #    context_count가 0이면 애초에 근거가 없던 것(검색 문제)이라 이 검사는 건너뛴다.
    if context_count > 0:
        coverage = len(cited) / context_count
        if coverage < MIN_CITATION_COVERAGE:
            return _verdict(IGNORES_CONTEXT)

    return _verdict(PASS)


def _verdict(outcome: str) -> QualityVerdict:
    """판정 코드로 QualityVerdict를 조립한다."""
    return QualityVerdict(
        outcome=outcome,
        should_regenerate=outcome in REGENERATABLE,
        reason=_DESCRIPTIONS.get(outcome, outcome),
        correction=_CORRECTIONS.get(outcome, ""),
    )
