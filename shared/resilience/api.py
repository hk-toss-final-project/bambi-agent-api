"""기능 영역의 공개 facade.

구현 모듈의 기능 함수를 안정적인 import 경로로 다시 노출한다.
"""

from .features.consistency import nfr_001
from .features.idempotency import nfr_002
from .features.schema_versions import nfr_003, nfr_004
from .features.content_versions import nfr_005, nfr_006, nfr_007, nfr_008
from .features.errors import nfr_009, nfr_010
from .features.messaging import nfr_011, nfr_012
from .features.degradation import nfr_013, nfr_017
from .features.scaling import nfr_014, nfr_015
from .features.backpressure import nfr_016
from .features.integrity import nfr_018, nfr_019
from .features.isolation import nfr_020
from .features.cost import nfr_021
from .features.performance import nfr_022

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
