"""Object Storage에 원문과 생성 Asset을 저장하는 공통 인터페이스."""

from dataclasses import dataclass
from typing import Mapping, Protocol


@dataclass(frozen=True, slots=True)
class StoredObject:
    """Object Storage에 저장된 파일의 위치와 무결성 정보."""

    key: str
    content_type: str
    size: int
    checksum: str


class ObjectStorage(Protocol):
    """대용량 원문과 생성 Asset의 저장·조회·삭제 경계."""

    async def put(
        self,
        key: str,
        content: bytes,
        metadata: Mapping[str, str],
    ) -> StoredObject:
        """파일과 Metadata를 저장하고 저장 결과를 반환한다."""
        ...

    async def get(self, key: str) -> bytes:
        """Object Key로 저장된 파일 내용을 조회한다."""
        ...

    async def delete(self, key: str) -> None:
        """보존 정책과 삭제 요청에 따라 저장된 파일을 제거한다."""
        ...
