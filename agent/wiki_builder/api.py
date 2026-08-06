"""기능 영역의 공개 facade.

구현 모듈의 기능 함수를 안정적인 import 경로로 다시 노출한다.
"""

from .features.orchestration import build_incremental_wiki, wba_001, wba_002
from .features.documents import wba_003, wba_004, wba_005
from .features.interests import wba_006, wba_007
from .features.summaries import wba_008, wba_009, wba_010
from .features.embeddings import generate_wiki_embeddings, wba_011
from .features.versioning import wba_012, wba_013
from .features.quality import wba_014
from .features.deletion import wba_015
from .features.events import wba_016
from .features.safeguards import wba_017
from .features.classification import (
    classify_source_for_wiki,
    classify_wiki_source,
    merge_wiki_classifications,
    parse_wiki_classification,
    split_source_content,
)
from .features.planning import build_wiki_plan

__all__ = [
    "wba_001",
    "wba_002",
    "wba_003",
    "wba_004",
    "wba_005",
    "wba_006",
    "wba_007",
    "wba_008",
    "wba_009",
    "wba_010",
    "wba_011",
    "wba_012",
    "wba_013",
    "wba_014",
    "wba_015",
    "wba_016",
    "wba_017",
]
