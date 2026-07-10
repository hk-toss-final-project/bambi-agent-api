"""LangGraph 기반 에이전트 그래프의 빌더 진입점."""


def build_personal_wiki_graph() -> object:
    """Personal Wiki Builder 노드와 엣지를 조립해 그래프를 생성한다."""
    raise NotImplementedError("Personal Wiki Builder 그래프 구현이 필요합니다.")


def build_bambi_generation_graph() -> object:
    """밤비 콘텐츠 생성 노드와 엣지를 조립해 그래프를 생성한다."""
    raise NotImplementedError("밤비 콘텐츠 생성 그래프 구현이 필요합니다.")


def build_quality_evaluation_graph() -> object:
    """콘텐츠 품질 평가와 재생성 분기 그래프를 생성한다."""
    raise NotImplementedError("품질 평가 그래프 구현이 필요합니다.")
