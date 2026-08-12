"""Personal Wiki 유지 루프 V3의 구조·의미 감사 LangGraph.

운영 Snapshot 신선도 감사와 현재 문서의 구조 Lint를 분리하고, 제한된 LLM 의미
감사로 모순·오래된 주장·누락 주제·누락 관계·외부 지식 공백을 찾는다. 내부
수리는 원자 저장하고 외부 자료는 기존 URL 수집·쓰기 루프로만 유입하며, 전체
재구성이 필요하면 내부 단계가 노드화된 V3 재구성 그래프를 실행한다.
"""

from __future__ import annotations

from asyncio import to_thread
from collections.abc import Awaitable, Callable, Mapping, Sequence
from dataclasses import dataclass
from typing import Any, NotRequired, TypedDict

from langgraph.graph import END, StateGraph
from langgraph.runtime import Runtime
from psycopg import AsyncConnection

from agent.llm.api import complete
from agent.report_builder.api import collect_live_context
from infrastructure.persistence.api import (
    UserSourceDocumentForAgent,
    list_existing_wiki_entries,
    list_existing_wiki_relations,
    list_user_source_versions_for_rebuild,
    register_url_and_enqueue,
    set_personal_wiki_scope,
    update_wiki_maintenance_summary,
)
from shared.report_models import ReportContextDocument
from shared.wiki_models import ExistingWikiEntry, WikiRelationPlan

from .embeddings import wba_011
from .full_rebuild_graph import run_wiki_full_rebuild_graph_v3
from .knowledge_gap_research import (
    WikiKnowledgeGapResearchResult,
    research_wiki_knowledge_gaps,
)
from .maintenance import (
    LANGGRAPH_MAINTENANCE_PIPELINE_V3_VERSION,
    WikiMaintenanceAction,
    WikiMaintenanceAudit,
    WikiMaintenancePlan,
    _audit_payload,
    load_wiki_maintenance_audit,
)
from .quality import WikiQualityReport, validate_wiki_quality
from .semantic_audit import (
    WikiSemanticCompletion,
    WikiSemanticLintReport,
    audit_wiki_semantics,
)
from .semantic_lint import (
    WikiSemanticLintContext,
    WikiSemanticSourceDocument,
    build_wiki_semantic_lint_context,
)
from .semantic_repairs import (
    WikiSemanticRepairPlan,
    WikiSemanticRepairResult,
    apply_wiki_semantic_repairs,
    plan_wiki_semantic_repairs,
)

type DictRow = dict[str, Any]
type WikiV3RebuildRunner = Callable[..., Awaitable[dict[str, object]]]
type WikiKnowledgeCollector = Callable[..., Sequence[ReportContextDocument]]
type WikiUrlRegistrar = Callable[..., Awaitable[Any]]

_STRUCTURAL_QUALITY_KEYS_V3 = (
    "error_count",
    "duplicate_document_count",
    "duplicate_surface_count",
    "unsupported_relation_count",
    "low_confidence_relation_count",
    "source_less_relation_count",
)


@dataclass(frozen=True, slots=True)
class WikiSemanticSnapshot:
    """한 의미 감사 실행에서 고정한 활성 원본·현재 Page·관계 Snapshot."""

    sources: tuple[UserSourceDocumentForAgent, ...]
    entries: tuple[ExistingWikiEntry, ...]
    relations: tuple[WikiRelationPlan, ...]


@dataclass(frozen=True, slots=True)
class WikiMaintenanceV3RuntimeContext:
    """V3 유지 노드가 공유하는 DB와 교체 가능한 외부 경계."""

    connection: AsyncConnection[DictRow]
    full_rebuild_runner: WikiV3RebuildRunner
    semantic_completion: WikiSemanticCompletion
    knowledge_collector: WikiKnowledgeCollector
    url_registrar: WikiUrlRegistrar


class WikiMaintenanceV3State(TypedDict):
    """V3 유지 그래프가 운영 감사부터 의미 수리까지 공유하는 상태."""

    user_id: str
    job_id: str
    trigger: str
    model: str
    embedding_model: str
    embedding_batch_threshold: int
    rebuild_performed: bool
    audit: NotRequired[WikiMaintenanceAudit]
    operational_plan: NotRequired[WikiMaintenancePlan]
    full_rebuild_result: NotRequired[dict[str, object]]
    snapshot: NotRequired[WikiSemanticSnapshot]
    structural_quality: NotRequired[WikiQualityReport]
    semantic_context: NotRequired[WikiSemanticLintContext]
    semantic_report: NotRequired[WikiSemanticLintReport]
    repair_plan: NotRequired[WikiSemanticRepairPlan]
    repair_result: NotRequired[WikiSemanticRepairResult]
    research_result: NotRequired[WikiKnowledgeGapResearchResult]
    derivative_embedding_count: NotRequired[int]
    derivative_warning: NotRequired[str | None]
    semantic_metrics: NotRequired[dict[str, int | float]]
    maintenance_action: NotRequired[str]
    result: NotRequired[dict[str, object]]


def _number(value: object) -> float:
    """품질 Metric 값을 비교 가능한 숫자로 안전하게 변환한다."""
    if isinstance(value, bool):
        return float(int(value))
    if isinstance(value, (int, float)):
        return float(value)
    return 0.0


def plan_wiki_maintenance_v3(
    audit: WikiMaintenanceAudit,
    *,
    trigger: str,
) -> WikiMaintenancePlan:
    """V3 의미 이슈와 구조 오류를 분리해 전체 재구성 필요 여부를 계획한다."""
    if trigger == "source_deleted":
        return WikiMaintenancePlan(
            WikiMaintenanceAction.FULL_REBUILD,
            "원본 제거를 파생 Wiki와 관계에 반영해야 합니다.",
        )
    if audit.source_count == 0:
        return WikiMaintenancePlan(
            WikiMaintenanceAction.FULL_REBUILD,
            "활성 원본이 없어 기존 Wiki 파생물을 retire해야 합니다.",
        )
    if audit.active_wiki_version_id is None:
        return WikiMaintenancePlan(
            WikiMaintenanceAction.FULL_REBUILD,
            "활성 Wiki Snapshot이 없습니다.",
        )
    if audit.active_wiki_activated_at is None:
        return WikiMaintenancePlan(
            WikiMaintenanceAction.FULL_REBUILD,
            "활성 Wiki의 교체 완료 시각이 없습니다.",
        )
    if not audit.quality_metrics:
        return WikiMaintenancePlan(
            WikiMaintenanceAction.FULL_REBUILD,
            "품질 Metric이 없는 과거 Snapshot의 기준선을 만들어야 합니다.",
        )
    if (
        audit.latest_source_updated_at is not None
        and audit.latest_source_updated_at > audit.active_wiki_activated_at
    ):
        return WikiMaintenancePlan(
            WikiMaintenanceAction.FULL_REBUILD,
            "활성 Wiki보다 최신인 사용자 원본이 있습니다.",
        )
    structural_issues = [
        key
        for key in _STRUCTURAL_QUALITY_KEYS_V3
        if _number(audit.quality_metrics.get(key)) > 0
    ]
    if structural_issues:
        return WikiMaintenancePlan(
            WikiMaintenanceAction.FULL_REBUILD,
            "구조 품질 이슈가 있습니다: " + ", ".join(structural_issues),
        )
    if audit.missing_embedding_document_version_ids:
        return WikiMaintenancePlan(
            WikiMaintenanceAction.REPAIR_DERIVATIVES,
            "의미 감사 후 누락 검색 Embedding을 복구해야 합니다.",
        )
    return WikiMaintenancePlan(
        WikiMaintenanceAction.NOOP,
        "운영 Snapshot은 최신이며 현재 구조·의미 감사를 진행합니다.",
    )


async def load_wiki_semantic_snapshot(
    connection: AsyncConnection[DictRow],
    *,
    user_id: str,
) -> WikiSemanticSnapshot:
    """활성 원본과 현재 Entity·Concept·관계를 한 조회 Transaction에서 고정한다."""
    async with connection.transaction():
        await set_personal_wiki_scope(connection, user_id=user_id)
        sources = await list_user_source_versions_for_rebuild(
            connection,
            user_id=user_id,
        )
        entries = [
            *await list_existing_wiki_entries(
                connection,
                user_id=user_id,
                document_kind="entity",
            ),
            *await list_existing_wiki_entries(
                connection,
                user_id=user_id,
                document_kind="concept",
            ),
        ]
        relations = await list_existing_wiki_relations(
            connection,
            namespace_key=f"user/{user_id}",
        )
    return WikiSemanticSnapshot(
        sources=tuple(sources),
        entries=tuple(entries),
        relations=tuple(relations),
    )


def _semantic_source(source: UserSourceDocumentForAgent) -> WikiSemanticSourceDocument:
    """활성 원본 Version을 제한 의미 감사 입력 값으로 변환한다."""
    return WikiSemanticSourceDocument(
        source_document_version_id=source.source_document_version_id,
        title=source.title,
        raw_content=source.raw_content or "",
        source_type=source.source_type,
        canonical_url=source.canonical_url,
        published_at=source.published_at,
        source_metadata=source.source_metadata,
    )


def _maintenance_action(state: WikiMaintenanceV3State) -> str:
    """V3 실행 결과에서 사용자 Wiki에 가장 큰 영향을 준 작업을 고른다."""
    if state["rebuild_performed"]:
        return WikiMaintenanceAction.FULL_REBUILD.value
    repair = state["repair_result"]
    if repair.repaired_issue_ids:
        return "semantic_repair"
    if state["research_result"].queued_source_count:
        return "research_enqueued"
    if state.get("derivative_embedding_count", 0):
        return WikiMaintenanceAction.REPAIR_DERIVATIVES.value
    return "semantic_audit"


def _semantic_metrics(state: WikiMaintenanceV3State) -> dict[str, int | float]:
    """의미 감사·수리·외부 조사 집계를 Snapshot 요약용 단일 Map으로 합친다."""
    report_metrics = dict(state["semantic_report"].metrics)
    plan_metrics = {
        f"repair_{key}": value
        for key, value in state["repair_plan"].metrics.items()
    }
    research = state["research_result"]
    return {
        **report_metrics,
        **plan_metrics,
        "repaired_issue_count": len(state["repair_result"].repaired_issue_ids),
        "research_query_count": research.query_count,
        "research_collected_document_count": research.collected_document_count,
        "research_queued_source_count": research.queued_source_count,
        "research_warning_count": len(research.warnings),
    }


def _summary_wiki_version_id(state: WikiMaintenanceV3State) -> str | None:
    """이번 실행에서 최종 활성화된 Wiki Version ID를 우선순위대로 찾는다."""
    if state["repair_result"].wiki_version_id:
        return state["repair_result"].wiki_version_id
    rebuilt = state.get("full_rebuild_result") or {}
    rebuilt_id = rebuilt.get("wiki_version_id")
    if rebuilt_id:
        return str(rebuilt_id)
    return state["audit"].active_wiki_version_id


def build_wiki_maintenance_graph_v3() -> Any:
    """운영·구조·의미 감사와 수리·조사·요약을 포함한 V3 그래프를 컴파일한다."""

    async def operational_audit(
        state: WikiMaintenanceV3State,
        runtime: Runtime[WikiMaintenanceV3RuntimeContext],
    ) -> dict[str, object]:
        """활성 원본·Snapshot 신선도·저장 품질 지표·누락 Embedding을 조회한다."""
        audit = await load_wiki_maintenance_audit(
            runtime.context.connection,
            user_id=state["user_id"],
            embedding_model=state["embedding_model"],
        )
        return {"audit": audit}

    async def plan_operational(state: WikiMaintenanceV3State) -> dict[str, object]:
        """운영 감사에서 즉시 전체 재구성이 필요한지 먼저 판정한다."""
        return {
            "operational_plan": plan_wiki_maintenance_v3(
                state["audit"],
                trigger=state["trigger"],
            )
        }

    def route_operational(state: WikiMaintenanceV3State) -> str:
        """전체 재구성 계획만 V3 재구성 서브그래프로 보내고 나머지는 감사한다."""
        return (
            "rebuild"
            if state["operational_plan"].action is WikiMaintenanceAction.FULL_REBUILD
            else "inspect"
        )

    async def full_rebuild(
        state: WikiMaintenanceV3State,
        runtime: Runtime[WikiMaintenanceV3RuntimeContext],
    ) -> dict[str, object]:
        """내부 단계가 노드화된 V3 전체 재구성 그래프를 한 번 실행한다."""
        if state["rebuild_performed"]:
            raise RuntimeError("V3 유지 Job에서 전체 재구성을 두 번 실행할 수 없습니다.")
        result = await runtime.context.full_rebuild_runner(
            runtime.context.connection,
            user_id=state["user_id"],
            job_id=state["job_id"],
            model=state["model"],
            embedding_model=state["embedding_model"],
            embedding_batch_threshold=state["embedding_batch_threshold"],
        )
        return {
            "full_rebuild_result": dict(result),
            "rebuild_performed": True,
        }

    async def load_snapshot(
        state: WikiMaintenanceV3State,
        runtime: Runtime[WikiMaintenanceV3RuntimeContext],
    ) -> dict[str, object]:
        """재구성 이후를 포함한 현재 활성 원본·Page·관계 Snapshot을 다시 고정한다."""
        snapshot = await load_wiki_semantic_snapshot(
            runtime.context.connection,
            user_id=state["user_id"],
        )
        return {"snapshot": snapshot}

    async def structural_lint(state: WikiMaintenanceV3State) -> dict[str, object]:
        """저장 요약이 아니라 현재 Page·관계를 결정적으로 다시 구조 감사한다."""
        snapshot = state["snapshot"]
        return {
            "structural_quality": validate_wiki_quality(
                snapshot.entries,
                snapshot.relations,
            )
        }

    def route_structural(state: WikiMaintenanceV3State) -> str:
        """구조 오류를 한 번 재구성하고 재구성 후에도 남으면 명시적으로 실패한다."""
        if state["structural_quality"].passed:
            return "healthy"
        return "fail" if state["rebuild_performed"] else "rebuild"

    async def structural_failure(state: WikiMaintenanceV3State) -> dict[str, object]:
        """V3 전체 재구성으로도 제거되지 않은 구조 오류를 요약해 실행을 중단한다."""
        errors = [
            issue.message
            for issue in state["structural_quality"].issues
            if issue.severity == "error"
        ]
        raise ValueError("V3 재구성 후 구조 품질 실패: " + "; ".join(errors[:5]))

    async def generate_candidates(state: WikiMaintenanceV3State) -> dict[str, object]:
        """Page·원본 상한과 전역 누락 관계 후보를 포함한 의미 감사 Context를 만든다."""
        snapshot = state["snapshot"]
        context = build_wiki_semantic_lint_context(
            snapshot.entries,
            snapshot.relations,
            [_semantic_source(source) for source in snapshot.sources],
        )
        return {"semantic_context": context}

    async def semantic_lint(
        state: WikiMaintenanceV3State,
        runtime: Runtime[WikiMaintenanceV3RuntimeContext],
    ) -> dict[str, object]:
        """제한 Context를 한 번 LLM 감사하고 모든 참조·인용을 코드로 재검증한다."""
        report = await to_thread(
            audit_wiki_semantics,
            state["semantic_context"],
            model=state["model"],
            completion=runtime.context.semantic_completion,
        )
        return {"semantic_report": report}

    async def plan_repairs(state: WikiMaintenanceV3State) -> dict[str, object]:
        """검증 문제를 내부 원자 수리와 외부 지식 공백 조사로 나눈다."""
        return {
            "repair_plan": plan_wiki_semantic_repairs(
                state["semantic_report"],
                context=state["semantic_context"],
            )
        }

    async def apply_internal_repairs(
        state: WikiMaintenanceV3State,
        runtime: Runtime[WikiMaintenanceV3RuntimeContext],
    ) -> dict[str, object]:
        """누락 주제·관계와 모순·오래된 주장 Metadata를 원자 수리한다."""
        snapshot = state["snapshot"]
        result = await apply_wiki_semantic_repairs(
            runtime.context.connection,
            user_id=state["user_id"],
            job_id=state["job_id"],
            repair_plan=state["repair_plan"],
            sources=snapshot.sources,
            entries=snapshot.entries,
            relations=snapshot.relations,
            model=state["semantic_report"].model,
            embedding_model=state["embedding_model"],
            embedding_batch_threshold=state["embedding_batch_threshold"],
        )
        return {"repair_result": result}

    async def research_knowledge_gaps(
        state: WikiMaintenanceV3State,
        runtime: Runtime[WikiMaintenanceV3RuntimeContext],
    ) -> dict[str, object]:
        """외부 지식 공백의 공개 URL을 기존 수집·쓰기 루프로 제한 등록한다."""
        result = await research_wiki_knowledge_gaps(
            runtime.context.connection,
            user_id=state["user_id"],
            job_id=state["job_id"],
            issues=state["repair_plan"].research_issues,
            model=state["model"],
            collector=runtime.context.knowledge_collector,
            registrar=runtime.context.url_registrar,
        )
        return {"research_result": result}

    async def repair_derivatives(
        state: WikiMaintenanceV3State,
        runtime: Runtime[WikiMaintenanceV3RuntimeContext],
    ) -> dict[str, object]:
        """전체 재구성을 하지 않은 경우 운영 감사에서 빠진 Embedding만 복구한다."""
        missing_ids = state["audit"].missing_embedding_document_version_ids
        if state["rebuild_performed"] or not missing_ids:
            return {
                "derivative_embedding_count": 0,
                "derivative_warning": None,
            }
        try:
            count = await wba_011(
                runtime.context.connection,
                namespace_key=f"user/{state['user_id']}",
                document_version_ids=missing_ids,
                model=state["embedding_model"],
                job_id=state["job_id"],
                batch_threshold=state["embedding_batch_threshold"],
            )
            return {
                "derivative_embedding_count": count,
                "derivative_warning": None,
            }
        except Exception as error:  # noqa: BLE001 - 내부 Wiki 수리는 이미 완료될 수 있음
            return {
                "derivative_embedding_count": 0,
                "derivative_warning": type(error).__name__,
            }

    async def persist_summary(
        state: WikiMaintenanceV3State,
        runtime: Runtime[WikiMaintenanceV3RuntimeContext],
    ) -> dict[str, object]:
        """구조·의미·수리·조사 집계를 최종 활성 Snapshot 요약에 병합한다."""
        metrics = _semantic_metrics(state)
        action = _maintenance_action(state)
        wiki_version_id = _summary_wiki_version_id(state)
        if wiki_version_id is not None:
            async with runtime.context.connection.transaction():
                await set_personal_wiki_scope(
                    runtime.context.connection,
                    user_id=state["user_id"],
                )
                await update_wiki_maintenance_summary(
                    runtime.context.connection,
                    user_id=state["user_id"],
                    wiki_version_id=wiki_version_id,
                    maintenance_pipeline_version=(
                        LANGGRAPH_MAINTENANCE_PIPELINE_V3_VERSION
                    ),
                    maintenance_action=action,
                    quality_metrics=state["repair_result"].quality.metrics,
                    semantic_metrics=metrics,
                )
        return {
            "semantic_metrics": metrics,
            "maintenance_action": action,
        }

    async def finalize(state: WikiMaintenanceV3State) -> dict[str, object]:
        """원문 없는 감사·수리·조사·Embedding 집계를 V3 Job 결과로 확정한다."""
        result = dict(state.get("full_rebuild_result") or {})
        result.update(
            {
                "maintenance_pipeline_version": (
                    LANGGRAPH_MAINTENANCE_PIPELINE_V3_VERSION
                ),
                "maintenance_action": state["maintenance_action"],
                "maintenance_reason": state["operational_plan"].reason,
                "maintenance_audit": _audit_payload(state["audit"]),
                "structural_quality_metrics": dict(
                    state["repair_result"].quality.metrics
                ),
                "semantic_lint": {
                    "model": state["semantic_report"].model,
                    "prompt_version": state["semantic_report"].prompt_version,
                    "metrics": dict(state["semantic_metrics"]),
                    "validation_warning_count": len(
                        state["semantic_report"].warnings
                    ),
                },
                "semantic_repair": {
                    "repaired_issue_count": len(
                        state["repair_result"].repaired_issue_ids
                    ),
                    "affected_document_count": (
                        state["repair_result"].affected_document_count
                    ),
                    "stored_relation_count": (
                        state["repair_result"].stored_relation_count
                    ),
                    "embedding_count": state["repair_result"].embedding_count,
                    "skipped_issue_count": len(
                        state["repair_plan"].skipped_issue_ids
                    ),
                    "warning_count": len(state["repair_plan"].warnings),
                },
                "knowledge_gap_research": {
                    "query_count": state["research_result"].query_count,
                    "collected_document_count": (
                        state["research_result"].collected_document_count
                    ),
                    "queued_source_count": (
                        state["research_result"].queued_source_count
                    ),
                    "warning_count": len(state["research_result"].warnings),
                },
                "derivative_embedding_count": state.get(
                    "derivative_embedding_count",
                    0,
                ),
                "derivative_warning": state.get("derivative_warning"),
            }
        )
        if state["repair_result"].wiki_version_id is not None:
            result["wiki_version_id"] = state["repair_result"].wiki_version_id
        return {"result": result}

    graph = StateGraph(
        WikiMaintenanceV3State,
        context_schema=WikiMaintenanceV3RuntimeContext,
    )
    graph.add_node("operational_audit", operational_audit)
    graph.add_node("plan_operational", plan_operational)
    graph.add_node("full_rebuild", full_rebuild)
    graph.add_node("load_snapshot", load_snapshot)
    graph.add_node("structural_lint", structural_lint)
    graph.add_node("structural_failure", structural_failure)
    graph.add_node("generate_candidates", generate_candidates)
    graph.add_node("semantic_lint", semantic_lint)
    graph.add_node("plan_repairs", plan_repairs)
    graph.add_node("apply_internal_repairs", apply_internal_repairs)
    graph.add_node("research_knowledge_gaps", research_knowledge_gaps)
    graph.add_node("repair_derivatives", repair_derivatives)
    graph.add_node("persist_summary", persist_summary)
    graph.add_node("finalize", finalize)
    graph.set_entry_point("operational_audit")
    graph.add_edge("operational_audit", "plan_operational")
    graph.add_conditional_edges(
        "plan_operational",
        route_operational,
        {"rebuild": "full_rebuild", "inspect": "load_snapshot"},
    )
    graph.add_edge("full_rebuild", "load_snapshot")
    graph.add_edge("load_snapshot", "structural_lint")
    graph.add_conditional_edges(
        "structural_lint",
        route_structural,
        {
            "healthy": "generate_candidates",
            "rebuild": "full_rebuild",
            "fail": "structural_failure",
        },
    )
    graph.add_edge("structural_failure", END)
    graph.add_edge("generate_candidates", "semantic_lint")
    graph.add_edge("semantic_lint", "plan_repairs")
    graph.add_edge("plan_repairs", "apply_internal_repairs")
    graph.add_edge("apply_internal_repairs", "research_knowledge_gaps")
    graph.add_edge("research_knowledge_gaps", "repair_derivatives")
    graph.add_edge("repair_derivatives", "persist_summary")
    graph.add_edge("persist_summary", "finalize")
    graph.add_edge("finalize", END)
    return graph.compile()


async def run_wiki_maintenance_graph_v3(
    connection: AsyncConnection[DictRow],
    *,
    user_id: str,
    job_id: str,
    trigger: str,
    model: str = "gpt-4.1-mini",
    embedding_model: str = "text-embedding-3-small",
    embedding_batch_threshold: int = 0,
    full_rebuild_runner: WikiV3RebuildRunner = run_wiki_full_rebuild_graph_v3,
    semantic_completion: WikiSemanticCompletion = complete,
    knowledge_collector: WikiKnowledgeCollector = collect_live_context,
    url_registrar: WikiUrlRegistrar = register_url_and_enqueue,
) -> dict[str, object]:
    """V3 유지 그래프를 실행해 기존 Worker가 완료할 Job 결과를 반환한다."""
    graph = build_wiki_maintenance_graph_v3()
    final = await graph.ainvoke(
        {
            "user_id": user_id,
            "job_id": job_id,
            "trigger": trigger,
            "model": model,
            "embedding_model": embedding_model,
            "embedding_batch_threshold": embedding_batch_threshold,
            "rebuild_performed": False,
        },
        context=WikiMaintenanceV3RuntimeContext(
            connection=connection,
            full_rebuild_runner=full_rebuild_runner,
            semantic_completion=semantic_completion,
            knowledge_collector=knowledge_collector,
            url_registrar=url_registrar,
        ),
    )
    result = final.get("result")
    if not isinstance(result, dict):
        raise RuntimeError("Wiki 유지 V3 그래프가 Job 결과를 반환하지 않았습니다.")
    return dict(result)


__all__ = [
    "LANGGRAPH_MAINTENANCE_PIPELINE_V3_VERSION",
    "WikiMaintenanceV3RuntimeContext",
    "WikiMaintenanceV3State",
    "WikiSemanticSnapshot",
    "build_wiki_maintenance_graph_v3",
    "load_wiki_semantic_snapshot",
    "plan_wiki_maintenance_v3",
    "run_wiki_maintenance_graph_v3",
]
