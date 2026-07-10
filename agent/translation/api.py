"""기능 영역의 공개 facade.

구현 모듈의 기능 함수를 안정적인 import 경로로 다시 노출한다.
"""

from .features.documents import tr_001, tr_002, tr_003, tr_004
from .features.multilingual import tr_005
from .features.personalization import tr_006
from .features.glossary import tr_007
from .features.citations import tr_008
from .features.evaluation import tr_009
from .features.versions import tr_010

__all__ = [
    "tr_001",
    "tr_002",
    "tr_003",
    "tr_004",
    "tr_005",
    "tr_006",
    "tr_007",
    "tr_008",
    "tr_009",
    "tr_010",
]
