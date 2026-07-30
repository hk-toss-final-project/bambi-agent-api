"""기능 구현 모듈.

PWIKI-002, PWIKI-004, PWIKI-005 기능의 실제 구현 위치를 제공한다.
"""

from __future__ import annotations

from collections.abc import Mapping
from datetime import datetime
from typing import TYPE_CHECKING, Any

from psycopg import AsyncConnection

from shared.contracts import FeatureRequest, FeatureResult
from shared.wiki_models import WikiBuildPlan

if TYPE_CHECKING:
    from infrastructure.persistence.api import (
        PersistedWikiBuild,
        UserSourceDocumentForAgent,
    )


# MVP: agent-api-mvp-scope.md에서 구현 대상으로 지정된 기능입니다.
async def pwiki_002(
    connection: AsyncConnection[dict[str, Any]],
    *,
    source: UserSourceDocumentForAgent,
    plan: WikiBuildPlan,
    job_id: str,
) -> PersistedWikiBuild:
    """[PWIKI-002] 개인 Wiki 문서 생성.

    사용자가 선택한 데이터를 Wiki 문서로 변환한다.
    """
    if not job_id:
        raise ValueError("PWIKI-002에 job_id가 필요합니다.")
    from infrastructure.persistence.api import db_003

    return await db_003(
        connection,
        source=source,
        plan=plan,
        job_id=job_id,
    )


async def pwiki_004(request: FeatureRequest) -> FeatureResult:
    """[PWIKI-004] 개인 Wiki 문서 수정.

    사용자 메모와 수정 내용을 Wiki 문서에 반영한다.
    """
    raise NotImplementedError("[PWIKI-004] 기능 구현이 필요합니다.")


# MVP: agent-api-mvp-scope.md에서 구현 대상으로 지정된 기능입니다.
async def pwiki_005(
    connection: AsyncConnection[dict[str, Any]],
    *,
    user_id: str,
    document_id: str,
    source_event_id: str,
    occurred_at: datetime | None = None,
    memo: str | None = None,
) -> Mapping[str, object]:
    """[PWIKI-005] 개인 Wiki 문서 삭제.

    사용자가 제거한 데이터를 Wiki 검색 대상에서 제외한다. delete 이벤트를
    기록하고 문서를 soft-delete하며 파생 Chunk를 검색에서 즉시 제외한다.
    이미 삭제된 문서 재요청은 `already_deleted=True`로 멱등 처리한다.
    삭제 정책 판단(권한·확인 UX)은 Service 계층이 소유하고 이 기능은 실행만
    담당한다. 삭제 SQL은 영속화 계층이 소유하므로 그 공개 함수에 위임한다.

    Args:
        connection: 사용자 Namespace가 설정된 비동기 DB 커넥션
        user_id: 문서 소유자 식별자
        document_id: 삭제할 Wiki 문서 식별자
        source_event_id: delete 이벤트 멱등 키
        occurred_at: 삭제 발생 시각 (없으면 서버 시각)
        memo: 삭제 사유 메모 (선택)

    Returns:
        삭제 결과(document_id·document_kind·already_deleted·검색 제외 Chunk 수)
    """
    from infrastructure.persistence.api import (
        delete_wiki_document_and_record_event,
    )

    return await delete_wiki_document_and_record_event(
        connection,
        user_id=user_id,
        document_id=document_id,
        source_event_id=source_event_id,
        occurred_at=occurred_at,
        memo=memo,
    )
