"""밤비 콘텐츠 생성 그래프에서 사용하는 노드 함수."""

from agent.state import AgentState


# MVP: BAMBI-004 개인 Wiki 검색 단계에서 구현합니다.
async def search_personal_wiki(state: AgentState) -> dict[str, object]:
    """사용자 관심사와 기존 지식을 개인 Wiki에서 검색한다."""
    raise NotImplementedError("개인 Wiki 검색 노드 구현이 필요합니다.")


# MVP: BAMBI-005 Global Source 검색 단계에서 구현합니다.
async def search_global_sources(state: AgentState) -> dict[str, object]:
    """콘텐츠 주제와 관련된 최신 외부 자료를 검색한다."""
    raise NotImplementedError("Global Source 검색 노드 구현이 필요합니다.")


# MVP: BAMBI-012 사용자 개인화 단계에서 구현합니다.
async def apply_personalization(state: AgentState) -> dict[str, object]:
    """관심사, 언어, 플랜과 비선호 설정을 생성 컨텍스트에 반영한다."""
    raise NotImplementedError("사용자 개인화 노드 구현이 필요합니다.")


# MVP: BAMBI-008 콘텐츠 요약 단계에서 구현합니다.
async def generate_content_summary(state: AgentState) -> dict[str, object]:
    """피드와 미리보기에 사용할 콘텐츠 요약을 생성한다."""
    raise NotImplementedError("콘텐츠 요약 생성 노드 구현이 필요합니다.")


# MVP: BAMBI-009 콘텐츠 본문 단계에서 구현합니다.
async def generate_content_body(state: AgentState) -> dict[str, object]:
    """사용자 플랜과 콘텐츠 유형에 맞는 본문을 생성한다."""
    raise NotImplementedError("콘텐츠 본문 생성 노드 구현이 필요합니다.")


# MVP: BAMBI-011 Citation 단계에서 구현합니다.
async def build_content_citations(state: AgentState) -> dict[str, object]:
    """생성 본문의 주장과 참조한 개인·공용 자료를 연결한다."""
    raise NotImplementedError("콘텐츠 Citation 노드 구현이 필요합니다.")


# MVP: BAMBI-018 후보 저장 단계에서 구현합니다.
async def save_generation_candidate(state: AgentState) -> dict[str, object]:
    """발행 전 생성 콘텐츠 후보와 버전을 Agent DB에 저장한다."""
    raise NotImplementedError("생성 콘텐츠 후보 저장 노드 구현이 필요합니다.")


# MVP: BAMBI-020 완료 이벤트 단계에서 구현합니다.
async def publish_content_ready(state: AgentState) -> dict[str, object]:
    """콘텐츠 준비 완료 이벤트를 Integration Event Bus에 발행한다."""
    raise NotImplementedError("Content Ready 이벤트 노드 구현이 필요합니다.")
