"""기능 영역의 공개 facade.

구현 모듈의 기능 함수를 안정적인 import 경로로 다시 노출한다.
"""

from .network import sec_001
from .authentication import sec_002, sec_012, sec_013
from .isolation import sec_003, sec_004
from .minimization import sec_005, sec_006
from .encryption import sec_007
from .secrets import sec_008, sec_009
from .prompt_injection import sec_010
from .safety import sec_011
from .deletion import sec_014, sec_015, sec_016, sec_017
from .retention import sec_018
from .audit import sec_019, sec_020

__all__ = [
    "sec_001",
    "sec_002",
    "sec_012",
    "sec_013",
    "sec_003",
    "sec_004",
    "sec_005",
    "sec_006",
    "sec_007",
    "sec_008",
    "sec_009",
    "sec_010",
    "sec_011",
    "sec_014",
    "sec_015",
    "sec_016",
    "sec_017",
    "sec_018",
    "sec_019",
    "sec_020",
]
