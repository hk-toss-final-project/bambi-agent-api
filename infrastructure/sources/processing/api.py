"""기능 영역의 공개 facade.

구현 모듈의 기능 함수를 안정적인 import 경로로 다시 노출한다.
"""

from .features.raw_storage import gsp_001
from .features.extractors import gsp_002, gsp_003
from .features.normalization import gsp_004, gsp_005
from .features.deduplication import gsp_006
from .features.quality import gsp_007
from .features.versioning import gsp_008
from .features.chunking import gsp_009
from .features.embeddings import gsp_010, gsp_011
from .features.trust import gsp_012
from .features.history import gsp_013
from .features.retention import gsp_014
from .features.safeguards import gsp_015

__all__ = [
    "gsp_001",
    "gsp_002",
    "gsp_003",
    "gsp_004",
    "gsp_005",
    "gsp_006",
    "gsp_007",
    "gsp_008",
    "gsp_009",
    "gsp_010",
    "gsp_011",
    "gsp_012",
    "gsp_013",
    "gsp_014",
    "gsp_015",
]
