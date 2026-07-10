"""기능 영역의 공개 facade.

구현 모듈의 기능 함수를 안정적인 import 경로로 다시 노출한다.
"""

from .sources import (
    rec_001,
    rec_002,
    rec_003,
    rec_004,
    rec_005,
    rec_006,
    rec_007,
    rec_008,
)
from .scoring import rec_009
from .explanations import rec_010
from .diversity import rec_011, rec_012
from .deduplication import rec_013
from .preferences import rec_014
from .persistence import rec_015
from .events import rec_016
from .feedback import rec_017
from .experiments import rec_018
from .safeguards import rec_019

__all__ = [
    "rec_001",
    "rec_002",
    "rec_003",
    "rec_004",
    "rec_005",
    "rec_006",
    "rec_007",
    "rec_008",
    "rec_009",
    "rec_010",
    "rec_011",
    "rec_012",
    "rec_013",
    "rec_014",
    "rec_015",
    "rec_016",
    "rec_017",
    "rec_018",
    "rec_019",
]
