"""Personal Wiki 유지 루프의 버전 라우팅과 LangGraph V2 구현.

V2는 현재 Wiki를 감사해 불필요한 전체 LLM 재분류를 건너뛰고, 파생 Embedding
누락은 부분 복구하며, 구조 재구성이 필요할 때만 검증된 V1 원자 교체 실행기를
호출한다.
"""

from __future__ import annotations

from collections.abc import Awaitable, Callable, Mapping
from dataclasses import dataclass
from datetime import datetime
from enum import StrEnum
from typing import Any, NotRequired, TypedDict

from langgraph.graph import END, StateGraph
from langgraph.runtime import Runtime
from psycopg import AsyncConnection

from infrastructure.persistence.api import set_personal_wiki_scope

from .embeddings import wba_011

type DictRow = dict[str, Any]
type WikiRebuildRunner = Callable[..., Awaitable[dict[str, object]]]

LEGACY_MAINTENANCE_PIPELINE_VERSION = "legacy_v1"
LANGGRAPH_MAINTENANCE_PIPELINE_VERSION = "langgraph_v2"
LANGGRAPH_MAINTENANCE_PIPELINE_V3_VERSION = "langgraph_v3"
MAINTENANCE_PIPELINE_VERSIONS = frozenset(
    {
        LEGACY_MAINTENANCE_PIPELINE_VERSION,
        LANGGRAPH_MAINTENANCE_PIPELINE_VERSION,
        LANGGRAPH_MAINTENANCE_PIPELINE_V3_VERSION,
    }
)

_STRUCTURAL_QUALITY_KEYS = (
    "error_count",
    "orphan_count",
    "duplicate_document_count",
    "duplicate_surface_count",
    "unsupported_relation_count",
    "low_confidence_relation_count",
    "source_less_relation_count",
    "contradiction_count",
)


class WikiMaintenanceAction(StrEnum):
    """유지 감사 결과로 선택할 최소 실행 범위."""

    NOOP = "noop"
    REPAIR_DERIVATIVES = "repair_derivatives"
    FULL_REBUILD = "full_rebuild"


@dataclass(frozen=True, slots=True)
class WikiMaintenanceAudit:
    """현재 원본·Wiki Snapshot·Embedding 상태의 유지보수 감사 결과."""

    user_id: str
    source_count: int
    latest_source_updated_at: datetime | None
    active_wiki_version_id: str | None
    active_wiki_activated_at: datetime | None
    quality_metrics: Mapping[str, int | float]
    missing_embedding_document_version_ids: tuple[str, ...] = ()


@dataclass(frozen=True, slots=True)
class WikiMaintenancePlan:
    """감사 결과에서 결정한 유지 실행 범위와 근거."""

    action: WikiMaintenanceAction
    reason: str


@dataclass(frozen=True, slots=True)
class WikiMaintenanceRuntimeContext:
    """유지 그래프 노드가 공유하는 DB 연결과 기존 원자 재구성 실행기."""

    connection: AsyncConnection[DictRow]
    rebuild_runner: WikiRebuildRunner


class WikiMaintenanceState(TypedDict):
    """LangGraph Wiki 유지 루프 V2가 노드 사이에서 갱신하는 상태."""

    user_id: str
    job_id: str
    trigger: str
    model: str
    embedding_model: str
    embedding_batch_threshold: int
    audit: NotRequired[WikiMaintenanceAudit]
    plan: NotRequired[WikiMaintenancePlan]
    execution_result: NotRequired[dict[str, object]]
    result: NotRequired[dict[str, object]]


def _number(value: object) -> float:
    """품질 Metric 값을 비교 가능한 숫자로 안전하게 변환한다."""
    if isinstance(value, bool):
        return float(int(value))
    if isinstance(value, (int, float)):
        return float(value)
    return 0.0


async def load_wiki_maintenance_audit(
    connection: AsyncConnection[DictRow],
    *,
    user_id: str,
    embedding_model: str,
) -> WikiMaintenanceAudit:
    """활성 원본·Wiki 품질·누락 Embedding을 짧은 조회 Transaction에서 감사한다."""
    async with connection.transaction():
        await set_personal_wiki_scope(connection, user_id=user_id)
        source_cursor = await connection.execute(
            """
            SELECT COUNT(*) AS source_count, MAX(updated_at) AS latest_updated_at
            FROM agent.user_source_documents
            WHERE user_id = %s
              AND status = 'active'
              AND deleted_at IS NULL
            """,
            (user_id,),
        )
        source_row = await source_cursor.fetchone()
        wiki_cursor = await connection.execute(
            """
            SELECT id::text AS wiki_version_id, activated_at, change_summary
            FROM agent.wiki_versions
            WHERE user_id = %s AND status = 'active'
            ORDER BY version DESC
            LIMIT 1
            """,
            (user_id,),
        )
        wiki_row = await wiki_cursor.fetchone()
        missing_ids: tuple[str, ...] = ()
        if wiki_row is not None:
            missing_cursor = await connection.execute(
                """
                SELECT DISTINCT snapshot.document_version_id::text AS version_id
                FROM agent.wiki_version_documents AS snapshot
                JOIN agent.wiki_chunks AS chunk
                  ON chunk.document_version_id = snapshot.document_version_id
                 AND chunk.namespace_key = snapshot.namespace_key
                 AND chunk.is_searchable
                WHERE snapshot.wiki_version_id = %s::uuid
                  AND NOT EXISTS (
                      SELECT 1
                      FROM agent.wiki_embeddings AS embedding
                      WHERE embedding.chunk_id = chunk.id
                        AND embedding.namespace_key = chunk.namespace_key
                        AND embedding.model_name = %s
                  )
                ORDER BY version_id
                """,
                (wiki_row["wiki_version_id"], embedding_model),
            )
            missing_ids = tuple(
                str(row["version_id"]) for row in await missing_cursor.fetchall()
            )
    source_count = int(source_row["source_count"]) if source_row is not None else 0
    summary = dict(wiki_row.get("change_summary") or {}) if wiki_row else {}
    raw_metrics = summary.get("quality_metrics")
    metrics = dict(raw_metrics) if isinstance(raw_metrics, Mapping) else {}
    return WikiMaintenanceAudit(
        user_id=user_id,
        source_count=source_count,
        latest_source_updated_at=(
            source_row.get("latest_updated_at") if source_row is not None else None
        ),
        active_wiki_version_id=(
            str(wiki_row["wiki_version_id"]) if wiki_row is not None else None
        ),
        active_wiki_activated_at=(
            wiki_row.get("activated_at") if wiki_row is not None else None
        ),
        quality_metrics=metrics,
        missing_embedding_document_version_ids=missing_ids,
    )


def plan_wiki_maintenance(
    audit: WikiMaintenanceAudit,
    *,
    trigger: str,
) -> WikiMaintenancePlan:
    """현재 상태와 트리거로 noop·파생 복구·전체 재구성 중 최소 범위를 고른다."""
    if trigger == "source_deleted":
        return WikiMaintenancePlan(
            WikiMaintenanceAction.FULL_REBUILD,
            "원본 제거를 파생 Wiki와 관계에 반영해야 합니다.",
        )
    if audit.source_count == 0:
        return WikiMaintenancePlan(
            WikiMaintenanceAction.FULL_REBUILD,
            "활성 원본이 없어 기존 Wiki를 안전하게 retire해야 합니다.",
        )
    if audit.active_wiki_version_id is None:
        return WikiMaintenancePlan(
            WikiMaintenanceAction.FULL_REBUILD,
            "활성 Wiki Snapshot이 없습니다.",
        )
    if audit.active_wiki_activated_at is None:
        return WikiMaintenancePlan(
            WikiMaintenanceAction.FULL_REBUILD,
            "활성 Wiki의 교체 완료 시각이 없어 신선도를 검증할 수 없습니다.",
        )
    if not audit.quality_metrics:
        return WikiMaintenancePlan(
            WikiMaintenanceAction.FULL_REBUILD,
            "품질 Metric이 없는 과거 Snapshot의 기준선을 만들어야 합니다.",
        )
    if (
        audit.latest_source_updated_at is not None
        and audit.active_wiki_activated_at is not None
        and audit.latest_source_updated_at > audit.active_wiki_activated_at
    ):
        return WikiMaintenancePlan(
            WikiMaintenanceAction.FULL_REBUILD,
            "활성 Wiki보다 최신인 사용자 원본이 있습니다.",
        )
    structural_issues = [
        key
        for key in _STRUCTURAL_QUALITY_KEYS
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
            "구조는 건강하지만 검색 Embedding이 누락됐습니다.",
        )
    return WikiMaintenancePlan(
        WikiMaintenanceAction.NOOP,
        "원본·구조·파생 검색 상태가 모두 최신입니다.",
    )


def _audit_payload(audit: WikiMaintenanceAudit) -> dict[str, object]:
    """감사 결과를 원문 없이 Job 결과에 저장 가능한 요약으로 변환한다."""
    return {
        "source_count": audit.source_count,
        "active_wiki_version_id": audit.active_wiki_version_id,
        "latest_source_updated_at": (
            audit.latest_source_updated_at.isoformat()
            if audit.latest_source_updated_at is not None
            else None
        ),
        "active_wiki_activated_at": (
            audit.active_wiki_activated_at.isoformat()
            if audit.active_wiki_activated_at is not None
            else None
        ),
        "quality_metrics": dict(audit.quality_metrics),
        "missing_embedding_document_count": len(
            audit.missing_embedding_document_version_ids
        ),
    }


def build_wiki_maintenance_graph_v2() -> Any:
    """Wiki 유지 루프 V2의 감사·계획·부분 복구·전체 재구성 그래프를 컴파일한다."""

    async def audit(
        state: WikiMaintenanceState,
        runtime: Runtime[WikiMaintenanceRuntimeContext],
    ) -> dict[str, object]:
        """현재 원본·활성 Snapshot·품질·Embedding 상태를 읽는다."""
        result = await load_wiki_maintenance_audit(
            runtime.context.connection,
            user_id=state["user_id"],
            embedding_model=state["embedding_model"],
        )
        return {"audit": result}

    async def plan(state: WikiMaintenanceState) -> dict[str, object]:
        """감사 결과에서 이번 Job이 실행할 최소 유지 범위를 결정한다."""
        return {
            "plan": plan_wiki_maintenance(
                state["audit"],
                trigger=state["trigger"],
            )
        }

    def route_after_plan(state: WikiMaintenanceState) -> str:
        """유지 계획의 action을 해당 실행 노드로 연결한다."""
        return state["plan"].action.value

    async def repair_derivatives(
        state: WikiMaintenanceState,
        runtime: Runtime[WikiMaintenanceRuntimeContext],
    ) -> dict[str, object]:
        """구조를 재분류하지 않고 활성 Page의 누락 Embedding만 복구한다."""
        audit_result = state["audit"]
        count = await wba_011(
            runtime.context.connection,
            namespace_key=f"user/{state['user_id']}",
            document_version_ids=(
                audit_result.missing_embedding_document_version_ids
            ),
            model=state["embedding_model"],
            job_id=state["job_id"],
            batch_threshold=state["embedding_batch_threshold"],
        )
        return {
            "execution_result": {
                "full_rebuild": False,
                "embedding_count": count,
                "repaired_document_count": len(
                    audit_result.missing_embedding_document_version_ids
                ),
            }
        }

    async def full_rebuild(
        state: WikiMaintenanceState,
        runtime: Runtime[WikiMaintenanceRuntimeContext],
    ) -> dict[str, object]:
        """기존 V1 원자 교체 실행기로 구조 전체를 안전하게 재구성한다."""
        result = await runtime.context.rebuild_runner(
            runtime.context.connection,
            user_id=state["user_id"],
            job_id=state["job_id"],
            model=state["model"],
            embedding_batch_threshold=state["embedding_batch_threshold"],
        )
        return {"execution_result": dict(result)}

    async def finalize(state: WikiMaintenanceState) -> dict[str, object]:
        """실행 결과에 계획 버전·근거·감사 요약을 더해 Job 결과를 확정한다."""
        plan_result = state["plan"]
        result = dict(state.get("execution_result") or {})
        result.update(
            {
                "maintenance_pipeline_version": (
                    LANGGRAPH_MAINTENANCE_PIPELINE_VERSION
                ),
                "maintenance_action": plan_result.action.value,
                "maintenance_reason": plan_result.reason,
                "maintenance_audit": _audit_payload(state["audit"]),
            }
        )
        return {"result": result}

    graph = StateGraph(
        WikiMaintenanceState,
        context_schema=WikiMaintenanceRuntimeContext,
    )
    graph.add_node("audit", audit)
    graph.add_node("plan", plan)
    graph.add_node("repair_derivatives", repair_derivatives)
    graph.add_node("full_rebuild", full_rebuild)
    graph.add_node("finalize", finalize)
    graph.set_entry_point("audit")
    graph.add_edge("audit", "plan")
    graph.add_conditional_edges(
        "plan",
        route_after_plan,
        {
            WikiMaintenanceAction.NOOP.value: "finalize",
            WikiMaintenanceAction.REPAIR_DERIVATIVES.value: "repair_derivatives",
            WikiMaintenanceAction.FULL_REBUILD.value: "full_rebuild",
        },
    )
    graph.add_edge("repair_derivatives", "finalize")
    graph.add_edge("full_rebuild", "finalize")
    graph.add_edge("finalize", END)
    return graph.compile()


async def run_wiki_maintenance_graph_v2(
    connection: AsyncConnection[DictRow],
    *,
    user_id: str,
    job_id: str,
    trigger: str,
    rebuild_runner: WikiRebuildRunner,
    model: str = "gpt-4.1-mini",
    embedding_model: str = "text-embedding-3-small",
    embedding_batch_threshold: int = 0,
) -> dict[str, object]:
    """Wiki 유지 V2 그래프를 실행해 완료 가능한 Job 결과를 반환한다."""
    graph = build_wiki_maintenance_graph_v2()
    final = await graph.ainvoke(
        {
            "user_id": user_id,
            "job_id": job_id,
            "trigger": trigger,
            "model": model,
            "embedding_model": embedding_model,
            "embedding_batch_threshold": embedding_batch_threshold,
        },
        context=WikiMaintenanceRuntimeContext(
            connection=connection,
            rebuild_runner=rebuild_runner,
        ),
    )
    result = final.get("result")
    if not isinstance(result, dict):
        raise RuntimeError("Wiki 유지 V2 그래프가 Job 결과를 반환하지 않았습니다.")
    return dict(result)


async def run_wiki_maintenance_for_version(
    connection: AsyncConnection[DictRow],
    *,
    pipeline_version: str = LEGACY_MAINTENANCE_PIPELINE_VERSION,
    user_id: str,
    job_id: str,
    trigger: str,
    rebuild_runner: WikiRebuildRunner,
    model: str = "gpt-4.1-mini",
    embedding_model: str = "text-embedding-3-small",
    embedding_batch_threshold: int = 0,
) -> dict[str, object]:
    """Job에 고정된 버전에 따라 V1·V2·V3 유지 루프를 실행한다."""
    if pipeline_version == LEGACY_MAINTENANCE_PIPELINE_VERSION:
        result = await rebuild_runner(
            connection,
            user_id=user_id,
            job_id=job_id,
            model=model,
            embedding_batch_threshold=embedding_batch_threshold,
        )
        return dict(result)
    if pipeline_version == LANGGRAPH_MAINTENANCE_PIPELINE_VERSION:
        return await run_wiki_maintenance_graph_v2(
            connection,
            user_id=user_id,
            job_id=job_id,
            trigger=trigger,
            rebuild_runner=rebuild_runner,
            model=model,
            embedding_model=embedding_model,
            embedding_batch_threshold=embedding_batch_threshold,
        )
    if pipeline_version == LANGGRAPH_MAINTENANCE_PIPELINE_V3_VERSION:
        from .maintenance_v3 import run_wiki_maintenance_graph_v3

        return await run_wiki_maintenance_graph_v3(
            connection,
            user_id=user_id,
            job_id=job_id,
            trigger=trigger,
            model=model,
            embedding_model=embedding_model,
            embedding_batch_threshold=embedding_batch_threshold,
        )
    raise ValueError(
        f"지원하지 않는 Wiki 유지 파이프라인 버전입니다: {pipeline_version}"
    )
