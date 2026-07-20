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


class BambiGenerationState(TypedDict):
    """Bambi Generation 그래프가 노드 사이에서 갱신하는 상태."""

    user_id: str
    job_id: str
    attempt_number: int
    topic: str
    content_type: str
    language: str
    model: str
    contexts: NotRequired[list[object]]
    generated: NotRequired[object]
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
