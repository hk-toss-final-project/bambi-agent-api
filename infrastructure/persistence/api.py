"""기능 영역의 공개 facade.

구현 모듈의 기능 함수를 안정적인 import 경로로 다시 노출한다.
"""

from .features.users import db_001
from .features.personal_wiki import (
    UserSourceDocumentForAgent,
    PersistedWikiBuild,
    PersistedWikiDocument,
    RegisteredUrlSource,
    SavedUserSourceVersion,
    WikiChunkForEmbedding,
    WikiEmbeddingValue,
    chunk_wiki_markdown,
    db_003,
    db_004,
    db_005,
    db_006,
    db_007,
    get_user_source_document_version_for_agent,
    get_wiki_chunks_for_embedding,
    list_existing_wiki_entries,
    list_existing_wiki_relations,
    mark_url_source_event,
    persist_wiki_build,
    persist_wiki_embeddings,
    register_user_url_source,
    save_user_url_document_version,
    set_personal_wiki_scope,
)
from .features.global_source import (
    GlobalArticleToFetch,
    GlobalCollectionRunRecord,
    GlobalCollectionSchedule,
    claim_global_articles_for_fetch,
    db_008,
    db_009,
    db_010,
    db_011,
    db_012,
    db_013,
    db_014,
    load_collection_runs,
    load_collection_schedule,
    load_collection_schedules,
    mark_global_article_fetch_failed,
    persist_collected_articles,
    save_fetched_article_content,
    set_collection_schedule_status,
    update_collection_schedule,
    upsert_collection_schedule,
)
from .features.generation import db_015, db_016, db_017, db_018, db_019, db_020
from .features.recommendation import db_021
from .features.configuration import db_022, db_023, db_024, db_025
from .features.jobs import (
    ClaimAgentJobsCommand,
    ClaimedAgentJob,
    CompleteAgentJobCommand,
    EnqueuedWikiBuildJob,
    FailAgentJobCommand,
    StoredAgentJob,
    claim_agent_job_by_id,
    claim_personal_wiki_jobs,
    claim_runnable_agent_jobs,
    complete_agent_job,
    db_026,
    defer_user_wiki_build_jobs,
    enqueue_personal_wiki_build_job,
    enqueue_url_collection_job,
    fail_agent_job,
    get_agent_job,
    list_runnable_agent_jobs,
    release_user_wiki_build_jobs,
    set_system_job_scope,
)
from .features.source_ingestion import (
    GeneratedContentNotFoundError,
    PersistedSourceSubmission,
    db_002,
    register_url_and_enqueue,
    save_content_mark_and_enqueue,
    save_fetched_url_and_enqueue,
    save_onboarding_seed_and_enqueue,
    save_web_clipping_and_enqueue,
)
from .features.generation_runtime import (
    PersistedGenerationSubmission,
    StaleContextVersionError,
    StoredUserContext,
    UserContextRequiredError,
    enqueue_report_generation_job,
    load_global_document_freshness,
    load_report_context,
    persist_report_generation,
    upsert_user_context_snapshot,
)
from .features.events import db_027
from .features.api_keys import db_028
from .features.usage import db_029
from .features.audit import db_030
from .features.interest_profiles import (
    ConnectionInterestProfileRepository,
    load_interest_documents_for_user,
    load_recent_feedback_signals_for_user,
    save_feedback_signals_for_user,
    save_interest_profile_for_user,
)
from .features.wiki_deletion import (
    WikiDocumentNotFoundError,
    delete_wiki_document_and_record_event,
)

__all__ = [
    "db_001",
    "db_002",
    "db_003",
    "db_004",
    "db_005",
    "db_006",
    "db_007",
    "db_008",
    "db_009",
    "db_010",
    "db_011",
    "db_012",
    "db_013",
    "db_014",
    "db_015",
    "db_016",
    "db_017",
    "db_018",
    "db_019",
    "db_020",
    "db_021",
    "db_022",
    "db_023",
    "db_024",
    "db_025",
    "db_026",
    "db_027",
    "db_028",
    "db_029",
    "db_030",
    "save_fetched_url_and_enqueue",
]
