"""기능 영역의 공개 facade.

구현 모듈의 기능 함수를 안정적인 import 경로로 다시 노출한다.
"""

from .features.extraction import int_001
from .features.expansion import (
    DEFAULT_EXPANSION_LIMIT,
    REASON_DISABLED,
    REASON_EXPANDED,
    REASON_NO_NEIGHBORS,
    QueryExpansion,
    expand_topic_queries,
)
from .features.scoring import int_005
from .features.recalculation import (
    ActiveWikiRequiredError,
    InterestProfileRepository,
    int_011,
)
from .features.bundles import (
    ActiveInterestRequiredError,
    InterestBundleNeighbor,
    InterestBundleRepository,
    InterestReportBundle,
    int_012,
    int_013,
)

__all__ = [
    "DEFAULT_EXPANSION_LIMIT",
    "QueryExpansion",
    "expand_topic_queries",
    "int_001",
    "int_005",
    "int_011",
    "int_012",
    "int_013",
    "ActiveInterestRequiredError",
    "InterestBundleNeighbor",
    "InterestBundleRepository",
    "InterestReportBundle",
]
