"""기능 영역의 공개 facade.

구현 모듈의 기능 함수를 안정적인 import 경로로 다시 노출한다.
"""

from .features.orchestration import (
    FullWikiRebuildResult,
    build_incremental_wiki,
    persist_claude_authored_wiki_entry,
    rebuild_full_wiki,
    wba_001,
    wba_002,
    wba_018,
)
from .features.documents import wba_003, wba_004, wba_005
from .features.interests import wba_006, wba_007
from .features.summaries import wba_008, wba_009, wba_010
from .features.embeddings import (
    apply_wiki_embedding_batch_result,
    enqueue_wiki_embedding_batches,
    generate_relation_query_embeddings,
    generate_wiki_embeddings,
    wba_011,
)
from .features.versioning import wba_012, wba_013
from .features.quality import (
    ALLOWED_WIKI_RELATION_TYPES,
    WikiQualityIssue,
    WikiQualityReport,
    validate_wiki_quality,
    wba_014,
)
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
from .features.relation_candidates import (
    RelationCandidateConfig,
    RelationCandidateQuery,
    RelationCandidateSignal,
    WikiGraphEdge,
    WikiNodeIdentity,
    WikiRelationCandidate,
    retrieve_wiki_relation_candidates,
)
from .features.relation_linking import (
    RELATION_LINKER_PROMPT_VERSION,
    build_relation_candidate_sets,
    link_wiki_relations,
)
from .features.graph_expansion import (
    GRAPH_EXPANSION_RELATION_TYPES,
    GraphExpansionResult,
    GraphExpansionScore,
    GraphMaturityPolicy,
    GraphMaturityReport,
    WikiGraphExpansionEdge,
    evaluate_graph_maturity,
    expand_wiki_graph,
)
from .features.identity_resolution import (
    WikiIdentityConflict,
    WikiIdentityOption,
    WikiIdentityResolutionResult,
    WikiResolutionDraft,
    normalize_wiki_surface,
    prepare_wiki_identity_resolution,
    resolve_wiki_identity_conflicts,
    validate_wiki_identity_quality,
)
from .features.onboarding_contexts import (
    CUSTOM_TOPIC_PROMPT_VERSION,
    ONBOARDING_CONTEXT_MODEL,
    resolve_onboarding_contexts,
)

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
    "wba_018",
    "FullWikiRebuildResult",
    "build_incremental_wiki",
    "persist_claude_authored_wiki_entry",
    "rebuild_full_wiki",
    "generate_relation_query_embeddings",
    "generate_wiki_embeddings",
    "apply_wiki_embedding_batch_result",
    "enqueue_wiki_embedding_batches",
    "classify_source_for_wiki",
    "classify_wiki_source",
    "merge_wiki_classifications",
    "parse_wiki_classification",
    "split_source_content",
    "build_wiki_plan",
    "ALLOWED_WIKI_RELATION_TYPES",
    "WikiQualityIssue",
    "WikiQualityReport",
    "validate_wiki_quality",
    "WikiIdentityConflict",
    "WikiIdentityOption",
    "WikiIdentityResolutionResult",
    "WikiResolutionDraft",
    "RelationCandidateConfig",
    "RelationCandidateQuery",
    "RelationCandidateSignal",
    "WikiGraphEdge",
    "WikiNodeIdentity",
    "WikiRelationCandidate",
    "retrieve_wiki_relation_candidates",
    "RELATION_LINKER_PROMPT_VERSION",
    "build_relation_candidate_sets",
    "link_wiki_relations",
    "GRAPH_EXPANSION_RELATION_TYPES",
    "GraphExpansionResult",
    "GraphExpansionScore",
    "GraphMaturityPolicy",
    "GraphMaturityReport",
    "WikiGraphExpansionEdge",
    "evaluate_graph_maturity",
    "expand_wiki_graph",
    "normalize_wiki_surface",
    "prepare_wiki_identity_resolution",
    "resolve_wiki_identity_conflicts",
    "validate_wiki_identity_quality",
    "CUSTOM_TOPIC_PROMPT_VERSION",
    "ONBOARDING_CONTEXT_MODEL",
    "resolve_onboarding_contexts",
]
