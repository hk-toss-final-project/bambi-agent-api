"""기능 영역의 공개 facade.

구현 모듈의 기능 함수를 안정적인 import 경로로 다시 노출한다.
"""

from .wiki import pwiki_001
from .commands import pwiki_002, pwiki_004, pwiki_005
from .queries import pwiki_003
from .versions import pwiki_006
from .provenance import pwiki_007
from .deduplication import pwiki_008
from .merging import pwiki_009
from .summarization import pwiki_010
from .normalization import pwiki_011
from .isolation import pwiki_012

__all__ = [
    "pwiki_001",
    "pwiki_002",
    "pwiki_004",
    "pwiki_005",
    "pwiki_003",
    "pwiki_006",
    "pwiki_007",
    "pwiki_008",
    "pwiki_009",
    "pwiki_010",
    "pwiki_011",
    "pwiki_012",
]
