"""LangGraph 에이전트가 공유하는 공통·그래프별 상태 타입."""

from typing import NotRequired, TypedDict


class PersonalWikiBuildState(TypedDict):
    """Personal Wiki Build 그래프가 노드 사이에서 갱신하는 상태."""

    user_id: str
    source_document_version_id: str
    job_id: str
    model: str
    source: NotRequired[object]
    existing_entities: NotRequired[list[object]]
    existing_concepts: NotRequired[list[object]]
    existing_relations: NotRequired[list[object]]
    onboarding_anchor_keys: NotRequired[list[tuple[str, str]]]
    node_embeddings: NotRequired[list[object]]
    taxonomy_contexts: NotRequired[list[object]]
    cached_custom_contexts: NotRequired[list[object]]
    onboarding_contexts: NotRequired[list[object]]
    generated_custom_contexts: NotRequired[list[object]]
    onboarding_context_model: NotRequired[str]
    onboarding_context_warnings: NotRequired[list[str]]
    classification: NotRequired[object]
    classification_model: NotRequired[str]
    resolution_draft: NotRequired[object]
    identity_resolution: NotRequired[object]
    identity_resolution_model: NotRequired[str]
    identity_conflict_count: NotRequired[int]
    identity_input_tokens: NotRequired[int]
    identity_output_tokens: NotRequired[int]
    relation_candidates: NotRequired[dict[str, list[object]]]
    relation_candidate_count: NotRequired[int]
    relation_recall_warnings: NotRequired[list[str]]
    relation_linker_model: NotRequired[str]
    plan: NotRequired[object]
    quality_metrics: NotRequired[dict[str, int | float]]
    quality_warnings: NotRequired[list[str]]
    persisted: NotRequired[object]
    embedding_count: NotRequired[int]
    embedding_warning: NotRequired[str | None]
    custom_context_cache_count: NotRequired[int]
    result: NotRequired[dict[str, object]]


class ReportGenerationState(TypedDict):
    """Report Builder Generation 그래프가 노드 사이에서 갱신하는 상태."""

    user_id: str
    job_id: str
    attempt_number: int
    topic: str
    # 한 리포트가 함께 다룰 주제 목록. 비어 있으면 topic 하나만 다룬다(기존 동작).
    # 값이 있으면 topic은 카드 제목·generation_topic 용도로만 남는다.
    topics: NotRequired[list[str]]
    # INTEREST_BUNDLE 요청은 접수 당시 활성 Profile과 Wiki 1홉 키워드를 고정해
    # 둔다. 실행 중 현재 Profile을 다시 조회하지 않아 같은 Job의 재시도가 같다.
    generation_scope: NotRequired[str]
    interest_bundle: NotRequired[dict[str, object]]
    # SINGLE_TOPIC/topics 요청도 접수 시 INT-013으로 활성 관심사와 매칭된 주제는
    # 이 dict에 그 주제의 INT-012 스냅샷을 담는다(키: 주제 문자열). 매칭 안 된
    # 주제는 키 자체가 없다 — interest-bundle-report-design.md §9.
    topic_interest_bundles: NotRequired[dict[str, dict[str, object]]]
    # Job 접수 시점에 고정한 활성 Wiki Build UUID. Navigator의 Locate·Read가
    # 재시도 중 현재 Head로 이동하지 않게 한다.
    wiki_version_id: NotRequired[str | None]
    # 첫 Reader 실행이 Topic별로 고정한 Page Version·관계·Source. 같은 Job의
    # 재시도는 새 Seed를 고르지 않고 이 Snapshot을 재사용한다.
    wiki_navigation_snapshots: NotRequired[dict[str, dict[str, object]]]
    # Job 접수 시 고정한 읽기 실행 버전. 키가 없는 과거 Job은 legacy_v1이다.
    read_pipeline_version: NotRequired[str]
    content_type: str
    language: str
    model: str
    # 조사원(Researcher) 노드가 채운다. research_documents가 비어 있으면
    # load_context가 기존 고정 경로(풀 검색 → 부족하면 수집)로 되돌아간다.
    research_documents: NotRequired[list[object]]
    research_notes: NotRequired[str]
    research_calls: NotRequired[list[dict[str, object]]]
    # 조사원이 실시간 수집을 이미 시도했는지. 고정 경로가 같은 수집을 한 번 더
    # 돌리지 않게 하는 표식이다(성공 여부가 아니라 시도 여부).
    research_collected_live: NotRequired[bool]
    topic_intent: NotRequired[str]
    # 주제별 성격 판정과 주제별 조사 결과. 여러 주제를 묶을 때 load_context가
    # 주제마다 근거 몫을 배정하려면 어느 문서가 어느 주제 것인지 알아야 한다.
    topic_intents: NotRequired[dict[str, str]]
    research_documents_by_topic: NotRequired[dict[str, list[object]]]
    # 근거를 실제로 확보한 주제만. 생성 프롬프트에는 이 목록만 넘긴다 —
    # 근거 없는 주제를 남기면 LLM이 그 섹션을 일반론으로 채운다.
    covered_topics: NotRequired[list[str]]
    contexts: NotRequired[list[object]]
    # 주제마다 실제로 배정된 근거. contexts를 주제별로 쪼갠 것이라 합집합은
    # contexts와 같다. 델타 경로가 주제별로 비교하려면 어느 근거가 어느 주제
    # 몫인지 알아야 한다 — 여러 주제를 묶는 경로에서만 채운다.
    contexts_by_topic: NotRequired[dict[str, list[object]]]
    # 주제별 근거 단계 건수(수집 → 선별 → 확보). 섹션이 빠졌을 때 어디서
    # 근거를 잃었는지 작업 결과로 확인하려고 남긴다.
    evidence_trace: NotRequired[list[dict[str, object]]]
    # 조사 노드의 주제별 도구 호출 수·소요 시간.
    research_stats: NotRequired[list[dict[str, object]]]
    # 변경점(Delta) 추적 토글. 요청이 켜서 보낼 때만 True이며, 기본값은 꺼짐이라
    # 이 키가 없으면 기존 generate 경로로 그대로 간다(회귀 0).
    change_history_enabled: NotRequired[bool]
    # 델타 경로 실행 요약(팩트 수·드롭 플래그 등). 개발 화면과 로그용이며,
    # 저장·발행되는 본문은 generated 하나뿐이다.
    change_history: NotRequired[dict[str, object]]
    generated: NotRequired[object]
    # 검토자(critic)가 재작성을 요구하면 채운다. generate 노드가 이 지시를 받아
    # 다시 쓰고, review_attempts가 상한에 닿으면 그대로 발행한다.
    review_correction: NotRequired[str]
    review_attempts: NotRequired[int]
    review_outcome: NotRequired[str]
    # 검토자가 남긴 지적 문장. 결과 코드만으로는 왜 못 고쳤는지 알 수 없다.
    review_problem: NotRequired[str]
    latency_ms: NotRequired[int]
    result: NotRequired[dict[str, object]]


class ChangeHistoryState(TypedDict):
    """변경점(Delta) 추적 서브그래프가 노드 사이에서 갱신하는 상태.

    report_builder가 만든 contexts를 그대로 입력으로 받고, 조립한 결과를
    `generated`에 담아 돌려준다 — 기존 review 노드가 읽는 키와 같은 이름이라
    상위 그래프가 값을 그대로 옮겨 담기만 하면 된다.
    """

    user_id: str
    job_id: str
    topic: str
    model: str
    reference_date: object
    contexts: list[object]
    # Base(직전 실행) 정보. prepare 노드가 채운다.
    base_summary: NotRequired[str]
    base_available: NotRequired[bool]
    base_run_id: NotRequired[str]
    is_first_run: NotRequired[bool]
    # Supervisor가 정한 다음 목적지. 조건부 엣지가 이 값을 읽는다.
    route: NotRequired[str]
    diff_facts: NotRequired[list[object]]
    diff_done: NotRequired[bool]
    diff_attempts: NotRequired[int]
    compose: NotRequired[object]
    compose_attempts: NotRequired[int]
    impact: NotRequired[object]
    impact_attempts: NotRequired[int]
    validation: NotRequired[object]
    validated: NotRequired[bool]
    # 재작업 후에도 실패해 드롭한 항목과 사유. 무한 루프 대신 남기는 흔적이다.
    dropped_flags: NotRequired[list[dict[str, object]]]
    duplicate_count: NotRequired[int]
    no_change: NotRequired[bool]
    quality_outcome: NotRequired[str]
    generated: NotRequired[object]
    run_id: NotRequired[str]
    stored_fact_count: NotRequired[int]
    # 워커 3개가 쓴 토큰 누적. 벤치마크 비용 기록과 재작업 비용 추적에 쓴다.
    input_tokens: NotRequired[int]
    output_tokens: NotRequired[int]


class AgentState(TypedDict):
    """Wiki Builder와 콘텐츠 생성 그래프가 단계별로 갱신하는 상태."""

    request_id: str
    user_id: str
    job_id: NotRequired[str]
    input: NotRequired[dict[str, object]]
    context: NotRequired[dict[str, object]]
    documents: NotRequired[list[dict[str, object]]]
    citations: NotRequired[list[dict[str, object]]]
    result: NotRequired[dict[str, object]]
    errors: NotRequired[list[str]]
