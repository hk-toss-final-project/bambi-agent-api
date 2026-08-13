"""기능 영역의 공개 facade.

구현 모듈의 기능 함수를 안정적인 import 경로로 다시 노출한다.
"""

from .features.briefing_topics import (
    DEFAULT_BRIEFING_CANDIDATE_LIMIT,
    DEFAULT_BRIEFING_TOPIC_COUNT,
    BriefingTopicSelection,
    CandidateMaterial,
    CandidateSource,
    InterestCandidate,
    InterestContext,
    build_interest_context,
    select_briefing_topics,
)
from .features.orchestration import report_001, report_022
from .features.context import report_012
from .features.retrieval import report_004, report_005, report_006
from .features.live_sources import (
    collect_live_context,
    related_keyword_fetch_limit,
    select_generation_context,
)
from .features.pool_context import (
    GLOBAL_NAMESPACE,
    PERSONAL_SCORE_FLOOR,
    POOL_TOPIC_SIMILARITY_FLOOR,
    is_pool_relevant,
    is_pool_sufficient,
    pool_topic_similarity,
    select_personal_documents,
    select_pool_documents,
)
from .features.critic import CriticVerdict, critic_enabled, review_report
from .features.researcher import (
    ResearchOutcome,
    merge_context_documents,
    navigation_packet_documents,
    research_agent_enabled,
    research_context,
    search_global_documents,
)
from .features.wiki_retrieval import embed_wiki_queries
from .features.read_loop import (
    LANGGRAPH_READ_PIPELINE_VERSION,
    LEGACY_READ_PIPELINE_VERSION,
    READ_PIPELINE_VERSIONS,
    build_wiki_read_graph_v2,
    research_context_for_version,
    run_wiki_read_graph_v2,
    select_wiki_seed_candidates,
)
from .features.generation import ReportContextDocument, GeneratedReportContent, report_008, report_009, report_010, generate_report_content, generate_report_content_with_quality, build_report_generation_prompt, ReportGenerationPrompt, normalize_content_tags, parse_report_generation
from .features.topic_focus import focus_documents_on_topic
from .features.topic_facets import generate_topic_facets
from .features.quality import QualityVerdict, evaluate_report
from .features.citations import report_011
from .features.persistence import report_018
from .features.events import report_020
from .features.safeguards import report_021
from .features.batch import (
    apply_report_generation_batch_result,
    report_context_from_mapping,
    stage_report_generation_batch,
)

__all__ = [
    "report_001",
    "report_012",
    "report_004",
    "report_005",
    "report_006",
    "report_008",
    "report_009",
    "report_010",
    "report_011",
    "report_018",
    "report_020",
    "report_021",
    "report_022",
    "build_report_generation_prompt",
    "ReportGenerationPrompt",
    "apply_report_generation_batch_result",
    "report_context_from_mapping",
    "stage_report_generation_batch",
    "merge_context_documents",
    "navigation_packet_documents",
    "search_global_documents",
    "embed_wiki_queries",
    "focus_documents_on_topic",
    "generate_topic_facets",
    "LANGGRAPH_READ_PIPELINE_VERSION",
    "LEGACY_READ_PIPELINE_VERSION",
    "READ_PIPELINE_VERSIONS",
    "build_wiki_read_graph_v2",
    "research_context_for_version",
    "run_wiki_read_graph_v2",
    "select_wiki_seed_candidates",
]
