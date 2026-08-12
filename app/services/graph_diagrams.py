"""에이전트 LangGraph 구조를 Mermaid 다이어그램 정의로 추출하는 서비스.

개발용 그래프 시각화 페이지(/dev/graphs)가 사용한다. 각 그래프를 구조 추출
목적으로만 빌드해 LangGraph 내장 `draw_mermaid()`로 정의 텍스트를 뽑는다.
그래프 구조는 코드로 고정돼 있으므로 프로세스당 1회만 추출해 재사용한다.
"""

from __future__ import annotations

from dataclasses import dataclass
from functools import lru_cache
from typing import Any

from agent.assistant.api import build_assistant_graph
from agent.change_history.api import build_change_history_graph
from agent.graph import build_personal_wiki_graph, build_report_generation_graph
from agent.report_builder.api import build_wiki_read_graph_v2
from agent.wiki_builder.api import (
    build_wiki_full_rebuild_graph_v3,
    build_wiki_maintenance_graph_v2,
)


@dataclass(frozen=True, slots=True)
class GraphNodeDescription:
    """그래프 노드 하나의 표시 이름과 기능 설명."""

    node_id: str
    title: str
    description: str


@dataclass(frozen=True, slots=True)
class GraphDiagram:
    """시각화 페이지에 표시할 그래프 하나의 정보."""

    slug: str
    title: str
    description: str
    mermaid: str
    nodes: tuple[GraphNodeDescription, ...]


_START_NODE = GraphNodeDescription(
    node_id="__start__",
    title="실행 시작",
    description="그래프 실행 요청을 받아 첫 작업 노드로 전달하는 LangGraph 시작점입니다.",
)
_END_NODE = GraphNodeDescription(
    node_id="__end__",
    title="실행 종료",
    description="모든 작업이 끝난 상태를 받아 그래프 실행을 완료하는 LangGraph 종료점입니다.",
)


def _mermaid_of(compiled: Any) -> str:
    """컴파일된 LangGraph에서 Mermaid 정의 텍스트를 추출한다."""
    return compiled.get_graph().draw_mermaid()


def _diagram(
    *,
    slug: str,
    title: str,
    description: str,
    compiled: Any,
    nodes: tuple[GraphNodeDescription, ...],
) -> GraphDiagram:
    """실제 그래프와 노드 설명의 정합성을 확인해 다이어그램 정보를 만든다."""
    documented_nodes = (_START_NODE, *nodes, _END_NODE)
    actual_ids = set(compiled.get_graph().nodes)
    documented_ids = {node.node_id for node in documented_nodes}
    if actual_ids != documented_ids:
        missing = sorted(actual_ids - documented_ids)
        unknown = sorted(documented_ids - actual_ids)
        raise ValueError(
            f"그래프 노드 설명이 실제 구조와 다릅니다: slug={slug}, "
            f"missing={missing}, unknown={unknown}"
        )
    return GraphDiagram(
        slug=slug,
        title=title,
        description=description,
        mermaid=_mermaid_of(compiled),
        nodes=documented_nodes,
    )


@lru_cache(maxsize=1)
def list_graph_diagrams() -> tuple[GraphDiagram, ...]:
    """등록된 에이전트 그래프의 Mermaid 정의를 추출해 반환한다.

    Wiki·Report·변경점 추적 그래프 빌더는 DB 연결을 인자로 받지만 빌드 시점에는
    연결을 사용하지 않고 노드 클로저만 구성하므로, 구조 추출에는 None을 넘긴다.
    이 전제는 tests/app/test_graph_views.py가 회귀를 감지한다.
    """
    return (
        _diagram(
            slug="personal-wiki",
            title="Personal Wiki Build",
            description=(
                "원본 조회(load_source) → 온보딩 컨텍스트 해석"
                "(resolve_onboarding_context) → 추출 분류(classify) → 표기 정규화와 "
                "후보 탐색(prepare_identity) → 충돌이 있을 때만 의미 판정"
                "(resolve_identity) → canonical 중복 품질 검증(quality_gate) → "
                "하이브리드 관계 후보(recall_candidates) → 관계 판정(link_relations) → "
                "반영 계획(plan) → Snapshot Lint(validate_plan) → "
                "문서·Chunk 저장(persist) → Vector 생성 또는 Batch 등록(embed) → "
                "Job 결과 조립(finalize)"
            ),
            compiled=build_personal_wiki_graph(None),
            nodes=(
                GraphNodeDescription(
                    node_id="load_source",
                    title="원본과 기존 Wiki 조회",
                    description=(
                        "원본 문서 Version과 기존 Entity·Concept·관계를 하나의 조회 "
                        "트랜잭션에서 읽고, 원문이 없으면 실행을 중단합니다."
                    ),
                ),
                GraphNodeDescription(
                    node_id="resolve_onboarding_context",
                    title="온보딩 Topic 컨텍스트 해석",
                    description=(
                        "정식 Topic은 Agent DB 시드를 읽고, 사용자 추가 키워드는 "
                        "별칭·기존 Wiki·캐시·LLM·일반론 폴백 순으로 해석합니다."
                    ),
                ),
                GraphNodeDescription(
                    node_id="classify",
                    title="Wiki 항목 추출·분류",
                    description=(
                        "트랜잭션 밖에서 원본 유형과 기존 Wiki 상태를 참고해 새 "
                        "Entity·Concept 후보만 추출하고 관계 판정은 후속 "
                        "Linker와 분리합니다."
                    ),
                ),
                GraphNodeDescription(
                    node_id="prepare_identity",
                    title="표기 정규화와 충돌 탐색",
                    description=(
                        "표기만 다른 동일 노드는 결정적으로 병합하고, 의미 판단이 "
                        "필요한 후보만 추려 resolve_identity 또는 quality_gate로 보냅니다."
                    ),
                ),
                GraphNodeDescription(
                    node_id="resolve_identity",
                    title="모호한 Identity 판정",
                    description=(
                        "의미 충돌 후보가 있을 때만 LLM을 한 번 호출해 기존 노드와 "
                        "합칠지 별도 노드로 둘지 판정합니다."
                    ),
                ),
                GraphNodeDescription(
                    node_id="quality_gate",
                    title="Canonical 품질 검증",
                    description=(
                        "canonical 중복과 잘못된 기존 key를 검사해 잘못된 Identity가 "
                        "저장 단계로 넘어가지 않게 막습니다."
                    ),
                ),
                GraphNodeDescription(
                    node_id="recall_candidates",
                    title="하이브리드 관계 후보 검색",
                    description=(
                        "정확 표면형·어휘·trigram·Embedding·Graph 1-hop·온보딩 "
                        "anchor를 합쳐 LLM이 검토할 기존 노드를 선별합니다."
                    ),
                ),
                GraphNodeDescription(
                    node_id="link_relations",
                    title="근거 기반 관계 판정",
                    description=(
                        "부분 Edge 유무와 무관하게 전체 후보를 검토하고, "
                        "유형·provenance·confidence·disposition을 확정합니다."
                    ),
                ),
                GraphNodeDescription(
                    node_id="plan",
                    title="Wiki 반영 계획 생성",
                    description=(
                        "분류 결과와 기존 Wiki 상태를 비교해 만들거나 갱신할 문서·관계·"
                        "Chunk·Snapshot의 Build 계획을 구성합니다."
                    ),
                ),
                GraphNodeDescription(
                    node_id="validate_plan",
                    title="Wiki Snapshot 품질 Lint",
                    description=(
                        "중복·고립·무근거·저신뢰·스타일 Edge와 과밀 Hub를 검사해 "
                        "오류가 있는 계획의 저장을 막습니다."
                    ),
                ),
                GraphNodeDescription(
                    node_id="persist",
                    title="Wiki 결과 저장",
                    description=(
                        "계획된 문서·관계·Chunk와 Build Snapshot을 하나의 저장 "
                        "트랜잭션으로 기록합니다."
                    ),
                ),
                GraphNodeDescription(
                    node_id="embed",
                    title="변경 Chunk Embedding 처리",
                    description=(
                        "변경된 Entity·Concept Chunk를 즉시 재임베딩하거나, 설정된 "
                        "임계값 이상이면 OpenAI Batch Item으로 등록합니다. 완료된 "
                        "Vector는 다음 Build의 의미 후보 recall에 사용됩니다."
                    ),
                ),
                GraphNodeDescription(
                    node_id="finalize",
                    title="Job 결과 조립",
                    description=(
                        "저장 결과와 Build 통계를 Job 결과 계약에 맞춰 조립하고, 변경된 "
                        "문서와 Identity 판정 사용량을 함께 반환합니다."
                    ),
                ),
            ),
        ),
        _diagram(
            slug="wiki-maintenance-v2",
            title="Wiki Maintenance Loop V2",
            description=(
                "현재 원본·활성 Snapshot·품질·Embedding 감사(audit) → 최소 실행 범위 "
                "결정(plan) → 건강하면 즉시 종료(noop), 파생 검색만 빠졌으면 "
                "Embedding 복구(repair_derivatives), 구조 이슈·원본 제거면 검증된 V1 "
                "원자 교체 실행기(full_rebuild) → 실행 버전·근거·감사 요약 확정"
                "(finalize). Scheduler는 이 그래프를 반복하지 않고 Job 등록만 담당한다."
            ),
            compiled=build_wiki_maintenance_graph_v2(),
            nodes=(
                GraphNodeDescription(
                    node_id="audit",
                    title="현재 Wiki 상태 감사",
                    description=(
                        "활성 원본 수와 최신 시각, 활성 Wiki의 WBA-014 품질 Metric, "
                        "현재 Embedding 모델에서 빠진 Page Version을 조회합니다."
                    ),
                ),
                GraphNodeDescription(
                    node_id="plan",
                    title="최소 유지 범위 계획",
                    description=(
                        "원본 제거·구조 품질·Snapshot 신선도·Embedding 누락을 코드로 "
                        "판정해 noop, repair_derivatives, full_rebuild 중 하나를 고릅니다."
                    ),
                ),
                GraphNodeDescription(
                    node_id="repair_derivatives",
                    title="파생 검색 자료 복구",
                    description=(
                        "Wiki 문서와 관계를 다시 분류하지 않고 누락된 Chunk Embedding만 "
                        "즉시 생성하거나 OpenAI Batch Item으로 등록합니다."
                    ),
                ),
                GraphNodeDescription(
                    node_id="full_rebuild",
                    title="원자적 전체 재구성",
                    description=(
                        "기존 V1 실행기를 어댑터로 호출해 순차 분류·Lint·최종 단일 "
                        "Transaction 교체 계약을 그대로 보존합니다."
                    ),
                ),
                GraphNodeDescription(
                    node_id="finalize",
                    title="유지 결과 확정",
                    description=(
                        "실행 결과에 V2 버전, 선택 action과 이유, 원문 없는 감사 요약을 "
                        "더해 Job 결과로 저장할 Payload를 만듭니다."
                    ),
                ),
            ),
        ),
        _diagram(
            slug="wiki-full-rebuild-v3",
            title="Wiki Full Rebuild V3",
            description=(
                "활성 원본 고정(load_manifest) → 원본별 선택·온보딩 해석·분류·"
                "identity·관계·계획을 LangGraph loop로 순차 누적 → 전체 Snapshot "
                "품질 검사 → 단일 Transaction 원자 교체 → Embedding → 결과 확정. "
                "활성 원본이 없으면 LLM 없이 retire 경로로 파생물을 내린다."
            ),
            compiled=build_wiki_full_rebuild_graph_v3(),
            nodes=(
                GraphNodeDescription(
                    node_id="load_manifest",
                    title="활성 원본 Manifest 고정",
                    description=(
                        "현재 활성 Source Version과 온보딩 taxonomy·캐시 의존성을 "
                        "짧은 조회 Transaction에서 한 번에 고정합니다."
                    ),
                ),
                GraphNodeDescription(
                    node_id="select_source",
                    title="다음 원본 선택",
                    description=(
                        "고정 Manifest를 순서대로 한 건씩 선택하고 원본별 임시 "
                        "identity·관계 상태를 초기화합니다."
                    ),
                ),
                GraphNodeDescription(
                    node_id="resolve_onboarding_context",
                    title="온보딩 Context 해석",
                    description=(
                        "온보딩 원본만 taxonomy·캐시·기존 Page·LLM 순서로 Topic을 "
                        "해석하고 이후 원자 저장할 캐시 후보를 누적합니다."
                    ),
                ),
                GraphNodeDescription(
                    node_id="classify_source",
                    title="원본 지식 분류",
                    description=(
                        "현재 원본에서 새 Entity·Concept 후보를 추출하고 원본 순서를 "
                        "보존해 다음 단계로 넘깁니다."
                    ),
                ),
                GraphNodeDescription(
                    node_id="prepare_identity",
                    title="Identity 후보 정규화",
                    description=(
                        "표면형으로 확정할 수 있는 중복을 먼저 병합하고 의미 판정이 "
                        "필요한 충돌만 분리합니다."
                    ),
                ),
                GraphNodeDescription(
                    node_id="resolve_identity",
                    title="Identity 의미 판정",
                    description=(
                        "모호한 충돌이 있을 때만 LLM으로 기존 canonical Page와의 "
                        "병합 여부를 판정합니다."
                    ),
                ),
                GraphNodeDescription(
                    node_id="validate_identity",
                    title="Identity 품질 검증",
                    description=(
                        "canonical 중복·잘못된 기존 Key·자기 관계를 검사해 현재 "
                        "원본의 분류를 확정합니다."
                    ),
                ),
                GraphNodeDescription(
                    node_id="recall_relations",
                    title="관계 후보 Recall",
                    description=(
                        "현재 분류 노드별 기존 Page와 온보딩 anchor 후보를 제한해 "
                        "관계 판정 입력을 구성합니다."
                    ),
                ),
                GraphNodeDescription(
                    node_id="link_relations",
                    title="근거 관계 판정",
                    description=(
                        "후보 전체를 검토해 원문 근거·provenance·confidence가 있는 "
                        "관계만 확정합니다."
                    ),
                ),
                GraphNodeDescription(
                    node_id="plan_source",
                    title="원본별 Build 계획",
                    description=(
                        "현재 분류를 문서·관계·Schema·Artifact 계획으로 변환하되 "
                        "아직 DB에는 쓰지 않습니다."
                    ),
                ),
                GraphNodeDescription(
                    node_id="accumulate_source",
                    title="메모리 Snapshot 누적",
                    description=(
                        "원본별 계획을 메모리 Snapshot에 반영하고 남은 원본이 있으면 "
                        "select_source로 되돌아갑니다."
                    ),
                ),
                GraphNodeDescription(
                    node_id="validate_snapshot",
                    title="전역 Snapshot 품질 Gate",
                    description=(
                        "모든 원본 계획을 합친 문서·관계의 중복·근거·신뢰도·Hub를 "
                        "검사해 오류가 있으면 저장을 중단합니다."
                    ),
                ),
                GraphNodeDescription(
                    node_id="atomic_persist",
                    title="단일 Transaction 원자 교체",
                    description=(
                        "품질을 통과한 전체 계획만 기존 Wiki와 교체하고 문서·관계·"
                        "Chunk·Snapshot·요약을 함께 Commit합니다."
                    ),
                ),
                GraphNodeDescription(
                    node_id="embed",
                    title="변경 Page Embedding",
                    description=(
                        "교체된 Entity·Concept의 변경 Chunk만 현재 모델로 즉시 처리하거나 "
                        "OpenAI Batch Item으로 등록합니다."
                    ),
                ),
                GraphNodeDescription(
                    node_id="retire_without_sources",
                    title="무원본 Wiki Retire",
                    description=(
                        "활성 원본이 없으면 LLM을 호출하지 않고 문서·관계·검색 Chunk와 "
                        "관심사 파생물을 비활성화합니다."
                    ),
                ),
                GraphNodeDescription(
                    node_id="finalize",
                    title="재구성 결과 확정",
                    description=(
                        "원자 교체 또는 retire 결과를 같은 Job Payload 계약으로 조립하고 "
                        "V3 실행 버전과 품질 지표를 남깁니다."
                    ),
                ),
            ),
        ),
        _diagram(
            slug="wiki-read-v2",
            title="Wiki Read Loop V2",
            description=(
                "고정 Snapshot 복원 또는 Wiki 후보 탐색(restore_or_locate) → "
                "결정적 Seed 선택(select_seed) → Page·관계·Source 읽기(navigate) → "
                "Global 저장 근거 조회(search_global) → 개수·관련성 판정(assess) → "
                "부족할 때만 실시간 수집 1회(collect_live) → Context·Trace와 "
                "Navigation Snapshot 확정(finalize). V1 Researcher Tool Loop와 같은 "
                "ResearchOutcome 계약을 반환하되 반복 LLM 도구 왕복을 제거한다."
            ),
            compiled=build_wiki_read_graph_v2(),
            nodes=(
                GraphNodeDescription(
                    node_id="restore_or_locate",
                    title="Snapshot 복원 또는 Wiki Locate",
                    description=(
                        "재시도 Snapshot이나 관심사 묶음의 고정 Seed를 우선 복원하고, "
                        "없을 때만 고정 Wiki Version에서 후보를 최대 30개 찾습니다."
                    ),
                ),
                GraphNodeDescription(
                    node_id="select_seed",
                    title="결정적 Wiki Seed 선택",
                    description=(
                        "질문과 제목·별칭·요약의 관련성, exact·alias와 RRF 순위를 "
                        "결합해 최대 3개 Page Version을 코드로 선택합니다."
                    ),
                ),
                GraphNodeDescription(
                    node_id="navigate",
                    title="Wiki Page와 근거 읽기",
                    description=(
                        "선택한 정확한 Page Version에서 검증 관계와 원본 Source, "
                        "저장 시각이 보존된 Context Packet을 구성합니다."
                    ),
                ),
                GraphNodeDescription(
                    node_id="search_global",
                    title="Global 저장 근거 조회",
                    description=(
                        "대표 주제와 Job 접수 시 고정된 연관 키워드로 미리 수집한 "
                        "Global 자료를 조회하고 중복을 제거합니다."
                    ),
                ),
                GraphNodeDescription(
                    node_id="assess",
                    title="근거 충분성 판정",
                    description=(
                        "Global 근거의 개수와 주제 관련성을 결정적으로 검사해 Live "
                        "수집이 필요한지 분기합니다."
                    ),
                ),
                GraphNodeDescription(
                    node_id="collect_live",
                    title="실시간 근거 보강",
                    description=(
                        "저장 근거가 부족한 경우에만 기존 실시간 수집기를 최대 한 번 "
                        "호출하고, 실패해도 이미 확보한 근거를 보존합니다."
                    ),
                ),
                GraphNodeDescription(
                    node_id="finalize",
                    title="Context와 Trace 확정",
                    description=(
                        "Wiki·Global·Live 근거를 합치고 첫 Navigation Packet을 Job의 "
                        "Topic Snapshot으로 저장해 재시도 입력을 고정합니다."
                    ),
                ),
            ),
        ),
        _diagram(
            slug="report-generation",
            title="Report Builder Generation",
            description=(
                "조사원 에이전트가 wiki_search·wiki_read로 개인 Wiki를 읽고 "
                "search_pool로 Global 저장 근거를 찾은 뒤, 코드가 부족 여부를 "
                "판정하고 여러 주제의 부족한 Live 근거를 제한 병렬 수집(research) "
                "→ 주제별 근거 집중·중복 "
                "제거·상한 배정(load_context) → 콘텐츠 생성(generate) 또는 변경점 "
                "추적(change_history) → 검토자 에이전트가 get_source·search_pool로 "
                "인용을 원문과 대조(review) → Citation·Snapshot 저장(persist). "
                "일반 리포트의 사실관계 문제는 최대 한 번 재생성하고, 조사 실패는 "
                "load_context의 고정 경로로, 변경점 추적 전체 실패는 generate로 "
                "복구한다."
            ),
            compiled=build_report_generation_graph(None),
            nodes=(
                GraphNodeDescription(
                    node_id="research",
                    title="근거 조사",
                    description=(
                        "조사원 에이전트가 주제별로 wiki_search·wiki_read·search_pool "
                        "도구를 사용해 근거를 모읍니다. 도구 루프가 끝나면 코드가 Global "
                        "근거의 개수와 관련성을 판정합니다. 다중 주제 V2는 DB 단계를 먼저 "
                        "끝내고 부족한 주제의 Live 수집만 최대 3개 병렬 실행하며, 실패하거나 "
                        "빈손이면 확보한 저장 근거를 보존합니다. REPORT-022가 같은 날짜·주제로 "
                        "준비한 근거가 있으면 해당 Topic의 조사 도구를 다시 호출하지 않습니다."
                    ),
                ),
                GraphNodeDescription(
                    node_id="load_context",
                    title="생성 Context 선별",
                    description=(
                        "단일 주제는 조사 결과나 고정 검색 경로에서 Context를 선별합니다. "
                        "여러 주제는 주제별 저장·실시간 근거를 모아 관련 문장만 남기고, "
                        "원본 Version·Chunk 기준 중복을 제외한 뒤 근거 상한을 배분하며 "
                        "근거 없는 주제는 생성에서 "
                        "제외합니다."
                    ),
                ),
                GraphNodeDescription(
                    node_id="generate",
                    title="리포트 본문 생성",
                    description=(
                        "트랜잭션 밖에서 LLM으로 제목·본문·태그·인용을 생성하고 무료 "
                        "품질 검사를 적용해 지연 시간과 함께 결과를 남깁니다."
                    ),
                ),
                GraphNodeDescription(
                    node_id="change_history",
                    title="변경점 리포트 생성",
                    description=(
                        "변경점 추적 토글이 켜졌을 때 일반 생성 대신 서브그래프로 직전 "
                        "보고서 이후의 변화를 만듭니다. 여러 주제는 근거를 확보한 주제마다 "
                        "따로 실행해 성공 결과를 합치고, 전부 실패했을 때만 generate로 "
                        "복구합니다."
                    ),
                ),
                GraphNodeDescription(
                    node_id="review",
                    title="인용·사실관계 검토",
                    description=(
                        "검토자 에이전트가 초안 인용을 원문과 대조합니다. 일반 리포트의 "
                        "사실관계 문제가 발견되면 교정 지시와 함께 최대 한 번 재생성합니다."
                    ),
                ),
                GraphNodeDescription(
                    node_id="persist",
                    title="리포트와 발행 정보 저장",
                    description=(
                        "생성 Run·후보·Citation·Snapshot·Outbox를 저장 트랜잭션에 기록하고 "
                        "최종 발행 결과 계약을 반환합니다."
                    ),
                ),
            ),
        ),
        _diagram(
            slug="change-history",
            title="변경점(Delta) 추적",
            description=(
                "Base 조회(prepare) → 판단(supervisor) → 팩트 추출·과거 대조"
                "(diff, search_base_facts 도구 보유) → 신규·갱신·유지 전체로 종합·"
                "타임라인 생성(compose) → 신규·갱신이 있을 때만 파급효과 추론"
                "(impact) → 전체 팩트의 정합성·날짜·인용 검증(validate, 코드) → "
                "정보요약과 변경점 섹션 조립(assemble, 코드) → 신규·갱신 팩트만 "
                "저장(store). 팩트를 하나도 추출하지 못하면 상위 그래프가 일반 "
                "생성으로 복구하고, 전부 유지인 경우에는 impact만 건너뛴다. 검증 "
                "문제가 난 워커는 한 번만 재작업하며 조립 결과는 상위 그래프의 "
                "review(Critic)로 이어진다."
            ),
            compiled=build_change_history_graph(None),
            nodes=(
                GraphNodeDescription(
                    node_id="prepare",
                    title="비교 기준 조회",
                    description=(
                        "직전 발행 Snapshot의 요약과 과거 델타 팩트를 한 조회 트랜잭션에서 "
                        "읽어 첫 실행 여부와 비교 기준을 준비합니다."
                    ),
                ),
                GraphNodeDescription(
                    node_id="supervisor",
                    title="다음 작업 결정",
                    description=(
                        "완료 상태·팩트 유무·변경 여부·실패·재작업 예산을 코드로 판단해 "
                        "diff, compose, impact, validate, assemble 중 다음 노드를 선택합니다. "
                        "팩트가 없으면 실패로 처리하고, 전부 유지면 impact를 건너뜁니다."
                    ),
                ),
                GraphNodeDescription(
                    node_id="diff",
                    title="오늘 팩트와 과거 기록 대조",
                    description=(
                        "오늘 근거에서 구조화된 팩트를 추출하고 과거 기록을 도구로 조회해 "
                        "신규·변경·중복 여부를 판정합니다."
                    ),
                ),
                GraphNodeDescription(
                    node_id="compose",
                    title="개요와 타임라인 생성",
                    description=(
                        "신규·갱신·유지 팩트 전체와 직전 보고서 요약을 사용해 현재 상황의 "
                        "Overview와 시간순 타임라인을 한 번의 LLM 호출로 작성합니다."
                    ),
                ),
                GraphNodeDescription(
                    node_id="impact",
                    title="파급효과와 확인 사항 추론",
                    description=(
                        "신규·갱신 팩트만 바탕으로 의미·파급효과·확인 사항을 추론하며, "
                        "필요하면 이 노드만 더 강한 모델을 사용합니다. 전부 유지인 "
                        "실행에서는 이 노드를 건너뜁니다."
                    ),
                ),
                GraphNodeDescription(
                    node_id="validate",
                    title="정합성 검증",
                    description=(
                        "팩트 연결, 타임라인 날짜 범위, 인용 마커를 결정적 코드로 검사하고 "
                        "문제가 난 워커와 교정 사유를 supervisor에 돌려줍니다."
                    ),
                ),
                GraphNodeDescription(
                    node_id="assemble",
                    title="정보요약 리포트 조립",
                    description=(
                        "전체 팩트로 만든 개요를 유지하고 신규·갱신만 변경점 섹션에 넣어 "
                        "Markdown으로 조립합니다. 전부 유지인 경우에도 정상 정보요약을 "
                        "만들고 기존 무료 품질 검사를 적용합니다."
                    ),
                ),
                GraphNodeDescription(
                    node_id="store",
                    title="델타 실행과 팩트 저장",
                    description=(
                        "이번 실행 메타데이터와 신규·갱신 팩트만 다음 실행의 비교 기준으로 "
                        "저장하고 유지 팩트는 중복 저장하지 않습니다. 저장 실패는 경고만 "
                        "남기고 보고서 발행은 계속합니다."
                    ),
                ),
            ),
        ),
        _diagram(
            slug="assistant",
            title="키워드 비서 리서치 에이전트",
            description=(
                "검색어 초기화(plan) → 수집·선별(select) → 결과가 빈약하면 "
                "검색어 재구성(reformulate) 후 재시도 → 보고서 작성(write_report)"
            ),
            compiled=build_assistant_graph(),
            nodes=(
                GraphNodeDescription(
                    node_id="plan",
                    title="첫 검색어 계획",
                    description=(
                        "입력 토픽을 첫 검색어로 정하고 시도 이력·오류·재구성 한도를 "
                        "초기화합니다. 결정적 코드이며 LLM을 호출하지 않습니다."
                    ),
                ),
                GraphNodeDescription(
                    node_id="select",
                    title="자료 수집·선별과 재시도 판단",
                    description=(
                        "검색 파이프라인으로 자료를 수집·선별하고 실패 원인과 남은 시도 "
                        "횟수를 분류해 재검색할지 보고서를 쓸지 결정합니다."
                    ),
                ),
                GraphNodeDescription(
                    node_id="reformulate",
                    title="검색어 재구성",
                    description=(
                        "결과 부족이 검색어로 해결될 수 있을 때 LLM으로 새 검색어를 "
                        "제안합니다. 빈 값·중복·과도하게 긴 제안은 재시도하지 않습니다."
                    ),
                ),
                GraphNodeDescription(
                    node_id="write_report",
                    title="브리핑 작성",
                    description=(
                        "선별 결과를 바탕으로 최종 Markdown 브리핑을 생성합니다. 근거만 "
                        "필요한 호출에서는 불필요한 LLM 생성을 건너뜁니다."
                    ),
                ),
            ),
        ),
    )


def get_graph_diagram(slug: str) -> GraphDiagram | None:
    """slug에 해당하는 그래프 다이어그램을 반환한다. 없으면 None."""
    for diagram in list_graph_diagrams():
        if diagram.slug == slug:
            return diagram
    return None
