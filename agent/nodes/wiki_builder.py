"""Personal Wiki Builder 그래프에서 사용하는 노드 함수."""

from agent.state import AgentState


# MVP: 개인 Wiki 문서 구성 단계에서 구현합니다.
async def normalize_wiki_document(state: AgentState) -> dict[str, object]:
    """선택된 사용자 데이터를 공통 개인 Wiki 문서 구조로 정규화한다."""
    raise NotImplementedError("Wiki 문서 정규화 노드 구현이 필요합니다.")


# MVP: PWIKI-008 문서 중복 제거 단계에서 구현합니다.
async def deduplicate_wiki_document(state: AgentState) -> dict[str, object]:
    """기존 개인 Wiki와 비교해 동일하거나 유사한 문서를 제거한다."""
    raise NotImplementedError("Wiki 문서 중복 제거 노드 구현이 필요합니다.")


# MVP: PWE-001 문서 Chunking 단계에서 구현합니다.
async def chunk_wiki_document(state: AgentState) -> dict[str, object]:
    """개인 Wiki 문서를 검색 가능한 의미 단위 Chunk로 나눈다."""
    raise NotImplementedError("Wiki 문서 Chunking 노드 구현이 필요합니다.")


# MVP: PWE-004, PWE-005 Embedding 단계에서 구현합니다.
async def embed_wiki_chunks(state: AgentState) -> dict[str, object]:
    """개인 Wiki Chunk의 Embedding을 생성하고 사용자 영역에 저장한다."""
    raise NotImplementedError("Wiki Embedding 노드 구현이 필요합니다.")


# MVP: INT-001, INT-002, INT-005 관심사 분류 단계에서 구현합니다.
async def classify_user_interests(state: AgentState) -> dict[str, object]:
    """개인 Wiki를 바탕으로 사용자 관심사와 점수를 계산한다."""
    raise NotImplementedError("관심사 분류 노드 구현이 필요합니다.")


# MVP: 개인 Wiki Builder 결과 저장 단계에서 구현합니다.
async def save_personal_wiki(state: AgentState) -> dict[str, object]:
    """구성된 개인 Wiki 문서, Chunk와 관심사 프로필을 저장한다."""
    raise NotImplementedError("개인 Wiki 저장 노드 구현이 필요합니다.")
