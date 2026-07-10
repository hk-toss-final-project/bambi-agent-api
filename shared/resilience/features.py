"""기능 영역의 공개 facade.

구현 모듈의 기능 함수를 안정적인 import 경로로 다시 노출한다.
"""

from .consistency import nfr_001
from .idempotency import nfr_002
from .schema_versions import nfr_003, nfr_004
from .content_versions import nfr_005, nfr_006, nfr_007, nfr_008
from .errors import nfr_009, nfr_010
from .messaging import nfr_011, nfr_012
from .degradation import nfr_013, nfr_017
from .scaling import nfr_014, nfr_015
from .backpressure import nfr_016
from .integrity import nfr_018, nfr_019
from .isolation import nfr_020
from .cost import nfr_021
from .performance import nfr_022

__all__ = [
    "nfr_001",
    "nfr_002",
    "nfr_003",
    "nfr_004",
    "nfr_005",
    "nfr_006",
    "nfr_007",
    "nfr_008",
    "nfr_009",
    "nfr_010",
    "nfr_011",
    "nfr_012",
    "nfr_013",
    "nfr_017",
    "nfr_014",
    "nfr_015",
    "nfr_016",
    "nfr_018",
    "nfr_019",
    "nfr_020",
    "nfr_021",
    "nfr_022",
]
