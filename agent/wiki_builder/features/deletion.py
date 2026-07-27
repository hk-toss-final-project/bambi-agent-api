"""기능 구현 모듈.

WBA-015 기능의 실제 구현 위치를 제공한다. 삭제 SQL은 영속화 계층
(infrastructure/persistence)의 delete_wiki_document_and_record_event가
소유하고, 이 기능 함수는 커넥션을 보유한 호출자(API Service·향후 이벤트
Worker)가 쓰는 공식 진입점이다.
"""

from collections.abc import Mapping
from datetime import datetime
from typing import Any

from psycopg import AsyncConnection

from infrastructure.persistence.api import delete_wiki_document_and_record_event

type DictRow = dict[str, Any]


# MVP: agent-api-mvp-scope.md에서 구현 대상으로 지정된 기능입니다.
async def wba_015(
    connection: AsyncConnection[DictRow],
    *,
    user_id: str,
    document_id: str,
    source_event_id: str,
    occurred_at: datetime | None = None,
    memo: str | None = None,
) -> Mapping[str, object]:
    """[WBA-015] Wiki 삭제 반영.

    삭제된 사용자 원천과 파생 데이터를 제거한다. delete 이벤트를 기록하고
    문서를 soft-delete하며 Chunk를 검색에서 제외한다. 같은 개념이 새
    클리핑으로 재등장하면 새 문서로 되살아난다(D1 잠정: 기본 부활).
    """
    return await delete_wiki_document_and_record_event(
        connection,
        user_id=user_id,
        document_id=document_id,
        source_event_id=source_event_id,
        occurred_at=occurred_at,
        memo=memo,
    )
