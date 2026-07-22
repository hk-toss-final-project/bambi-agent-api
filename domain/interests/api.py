"""기능 영역의 공개 facade.

구현 모듈의 기능 함수를 안정적인 import 경로로 다시 노출한다.
"""

from .features.extraction import int_001
from .features.classification import int_002
from .features.graph import int_003, int_004
from .features.scoring import int_005, int_006, int_008, int_009
from .features.evidence import int_007
from .features.versioning import int_010
from .features.recalculation import (
    ActiveWikiRequiredError,
    InterestProfileRepository,
    int_011,
)

__all__ = [
    "int_001",
    "int_002",
    "int_003",
    "int_004",
    "int_005",
    "int_006",
    "int_008",
    "int_009",
    "int_007",
    "int_010",
    "int_011",
]
