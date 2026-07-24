"""기능 영역의 공개 facade.

구현 모듈의 기능 함수를 안정적인 import 경로로 다시 노출한다.
"""

from .features.orchestration import report_001, report_002
from .features.context import report_003, report_012
from .features.retrieval import report_004, report_005, report_006
from .features.live_sources import collect_live_context, select_generation_context
from .features.generation import (
    ReportContextDocument,
    GeneratedReportContent,
    report_007,
    report_008,
    report_009,
    report_010,
    generate_report_content,
    generate_report_content_with_quality,
    parse_report_generation,
)
from .features.citations import report_011
from .features.validation import report_013, report_014, report_015, report_016
from .features.versioning import report_017
from .features.persistence import report_018, report_019
from .features.events import report_020
from .features.safeguards import report_021

__all__ = [
    "report_001",
    "report_002",
    "report_003",
    "report_012",
    "report_004",
    "report_005",
    "report_006",
    "report_007",
    "report_008",
    "report_009",
    "report_010",
    "report_011",
    "report_013",
    "report_014",
    "report_015",
    "report_016",
    "report_017",
    "report_018",
    "report_019",
    "report_020",
    "report_021",
]
