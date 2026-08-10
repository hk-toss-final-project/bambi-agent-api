"""기능 영역의 공개 facade.

구현 모듈의 기능 함수를 안정적인 import 경로로 다시 노출한다.
"""

from .features.context import svc_001
from .features.wiki import svc_002, svc_003, svc_004, svc_005, svc_006, svc_007
from .features.generation import svc_008
from .features.summarization import svc_009
from .features.translation import svc_010
from .features.recommendation import svc_011
from .features.admin import svc_012
from .features.jobs import svc_013, svc_014, svc_015

__all__ = [
    "svc_001",
    "svc_002",
    "svc_003",
    "svc_004",
    "svc_005",
    "svc_006",
    "svc_007",
    "svc_008",
    "svc_009",
    "svc_010",
    "svc_011",
    "svc_012",
    "svc_013",
    "svc_014",
    "svc_015",
]
