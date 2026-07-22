"""개인 Wiki 검색 결과를 LLM Context로 구성하는 기능 구현."""

from collections.abc import Sequence

from shared.bambi_models import BambiContextDocument


# MVP: agent-api-mvp-scope.md에서 구현 대상으로 지정된 기능입니다.
async def prag_006(
    contexts: Sequence[BambiContextDocument],
) -> list[BambiContextDocument]:
    """[PRAG-006] 개인 Wiki Context 구성.

    LLM 입력에 사용할 개인 Wiki Context를 구성한다.
    """
    result: list[BambiContextDocument] = []
    references: set[str] = set()
    for context in contexts:
        if not context.reference.strip():
            raise ValueError("PRAG-006 Context에 참조 ID가 필요합니다.")
        if context.reference in references:
            raise ValueError(
                f"PRAG-006 Context 참조 ID가 중복되었습니다: {context.reference}"
            )
        if not context.content.strip():
            continue
        references.add(context.reference)
        result.append(context)
    return result
