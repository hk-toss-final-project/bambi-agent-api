"""기능 영역의 공개 facade.

구현 모듈의 기능 함수를 안정적인 import 경로로 다시 노출한다.
"""

from .features.assembly import (
    CHANGED_SUBHEADING,
    IMPLICATIONS_HEADING,
    NEW_SUBHEADING,
    OVERVIEW_HEADING,
    TIMELINE_HEADING,
    UPDATES_HEADING,
    assemble_delta_report,
    build_delta_markdown,
    chg_006,
    collect_allowed_citations,
)
from .features.compose import ComposeOutcome, TimelineDraft, chg_003
from .features.config import change_history_available, impact_model
from .features.dates import is_plausible_date, parse_absolute_date
from .features.diff import DiffFact, DiffOutcome, chg_002, parse_diff_facts
from .features.graph import (
    QUALITY_SKIPPED_NO_CHANGE,
    build_change_history_graph,
    chg_001,
)
from .features.impact import ImpactOutcome, chg_004
from .features.validation import (
    COMPOSE_WORKER,
    DIFF_WORKER,
    IMPACT_WORKER,
    ValidatedFact,
    ValidationOutcome,
    ValidationProblem,
    chg_005,
    has_valid_citation,
)

__all__ = [
    "chg_001",
    "chg_002",
    "chg_003",
    "chg_004",
    "chg_005",
    "chg_006",
    "ComposeOutcome",
    "DiffFact",
    "DiffOutcome",
    "ImpactOutcome",
    "TimelineDraft",
    "ValidatedFact",
    "ValidationOutcome",
    "ValidationProblem",
    "CHANGED_SUBHEADING",
    "COMPOSE_WORKER",
    "DIFF_WORKER",
    "IMPACT_WORKER",
    "IMPLICATIONS_HEADING",
    "NEW_SUBHEADING",
    "QUALITY_SKIPPED_NO_CHANGE",
    "OVERVIEW_HEADING",
    "TIMELINE_HEADING",
    "UPDATES_HEADING",
    "assemble_delta_report",
    "build_change_history_graph",
    "build_delta_markdown",
    "change_history_available",
    "collect_allowed_citations",
    "has_valid_citation",
    "impact_model",
    "is_plausible_date",
    "parse_absolute_date",
    "parse_diff_facts",
]
