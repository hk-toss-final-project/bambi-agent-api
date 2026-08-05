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
    classification: NotRequired[object]
    plan: NotRequired[object]
    persisted: NotRequired[object]
    result: NotRequired[dict[str, object]]


class ReportGenerationState(TypedDict):
    """Report Builder Generation 그래프가 노드 사이에서 갱신하는 상태."""

    user_id: str
    job_id: str
    attempt_number: int
    topic: str
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
    contexts: NotRequired[list[object]]
    generated: NotRequired[object]
    # 검토자(critic)가 재작성을 요구하면 채운다. generate 노드가 이 지시를 받아
    # 다시 쓰고, review_attempts가 상한에 닿으면 그대로 발행한다.
    review_correction: NotRequired[str]
    review_attempts: NotRequired[int]
    review_outcome: NotRequired[str]
    latency_ms: NotRequired[int]
    result: NotRequired[dict[str, object]]


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
