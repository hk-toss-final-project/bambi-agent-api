"""Obsidian Web Clipper Markdown에서 로컬 PostgreSQL Seed SQL을 생성한다."""

from __future__ import annotations

import argparse
import hashlib
import json
import re
import sys
import uuid
from dataclasses import dataclass
from datetime import date, datetime
from pathlib import Path
from urllib.parse import urlparse

PROJECT_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_INPUT_DIR = PROJECT_ROOT / "dummy" / "clippings"
DEFAULT_OUTPUT_PATH = PROJECT_ROOT / "database" / "seeds" / "0003_dev_web_clippings.sql"
SEED_NAMESPACE = uuid.UUID("7aa5c090-73ce-4ef8-a288-70a625f8613c")
MOCK_USER_ID = "mock-clipping-user"
SEED_USER_IDS = (MOCK_USER_ID, "28")


@dataclass(frozen=True)
class Clipping:
    """Seed 한 건에 필요한 클리핑 원문을 보관한다."""

    path: Path
    title: str
    source: str
    author: str | None
    published_at: str | None
    clipped_on: str
    description: str | None
    tags: tuple[str, ...]
    content: str
    content_hash: str
    source_event_key: str


@dataclass(frozen=True)
class SeedIdentifiers:
    """사용자별 Seed Row를 연결하는 결정적 UUID를 보관한다."""

    job_id: uuid.UUID
    event_id: uuid.UUID
    source_document_id: uuid.UUID
    source_version_id: uuid.UUID


def _parse_scalar(value: str) -> str | None:
    """제한된 Frontmatter Scalar를 문자열 또는 NULL 의미로 변환한다."""
    value = value.strip()
    if not value or value in {"null", "~"}:
        return None
    if value.startswith('"') and value.endswith('"'):
        parsed = json.loads(value)
        if not isinstance(parsed, str):
            raise ValueError(f"문자열 Frontmatter가 아닙니다: {value}")
        return parsed
    if value.startswith("'") and value.endswith("'"):
        return value[1:-1].replace("''", "'")
    return value


def _parse_frontmatter(lines: list[str]) -> dict[str, str | list[str] | None]:
    """Obsidian Clipper가 만든 단순 YAML Frontmatter를 해석한다."""
    result: dict[str, str | list[str] | None] = {}
    list_key: str | None = None

    for line in lines:
        if match := re.match(r"^  -\s+(.*)$", line):
            if list_key is None:
                raise ValueError(f"소속 Key가 없는 YAML 목록입니다: {line}")
            item = _parse_scalar(match.group(1))
            if item is not None:
                current = result.get(list_key)
                if current is None:
                    current = []
                    result[list_key] = current
                if not isinstance(current, list):
                    raise ValueError(f"Scalar와 목록이 혼합됐습니다: {list_key}")
                current.append(item)
            continue

        match = re.match(r"^([a-z_]+):(?:\s*(.*))?$", line)
        if match is None:
            if line.strip():
                raise ValueError(f"지원하지 않는 Frontmatter 줄입니다: {line}")
            continue

        key, raw_value = match.groups()
        list_key = key if not raw_value else None
        result[key] = _parse_scalar(raw_value or "")

    return result


def _as_optional_text(value: str | list[str] | None) -> str | None:
    """Scalar 또는 YAML 목록을 DB의 선택 Text 값으로 정규화한다."""
    if isinstance(value, list):
        joined = ", ".join(item.strip() for item in value if item.strip())
        return joined or None
    if value is None:
        return None
    stripped = value.strip()
    return stripped or None


def _as_tags(value: str | list[str] | None) -> tuple[str, ...]:
    """Tag 값을 공백과 중복이 제거된 순서 보존 Tuple로 변환한다."""
    values = value if isinstance(value, list) else ([value] if value else [])
    return tuple(dict.fromkeys(item.strip() for item in values if item and item.strip()))


def _normalize_published_at(value: str | list[str] | None) -> str | None:
    """게시 날짜를 PostgreSQL timestamptz에 넣을 ISO 8601 문자열로 변환한다."""
    text = _as_optional_text(value)
    if text is None:
        return None
    if re.fullmatch(r"\d{4}-\d{2}-\d{2}", text):
        date.fromisoformat(text)
        return f"{text}T00:00:00Z"
    datetime.fromisoformat(text.replace("Z", "+00:00"))
    return text


def _deterministic_uuid(kind: str, source: str) -> uuid.UUID:
    """Source URL과 Entity 종류로 재생성 가능한 UUID를 만든다."""
    return uuid.uuid5(SEED_NAMESPACE, f"{kind}:{source}")


def _user_deterministic_uuid(kind: str, source: str, user_id: str) -> uuid.UUID:
    """기존 Mock UUID를 보존하면서 사용자별로 격리된 UUID를 만든다."""
    if user_id == MOCK_USER_ID:
        return _deterministic_uuid(kind, source)
    return uuid.uuid5(SEED_NAMESPACE, f"{kind}:{user_id}:{source}")


def _seed_identifiers(clipping: Clipping, user_id: str) -> SeedIdentifiers:
    """클리핑과 사용자에 대응하는 Seed 식별자 묶음을 만든다."""
    return SeedIdentifiers(
        job_id=_user_deterministic_uuid("job", clipping.source, user_id),
        event_id=_user_deterministic_uuid("event", clipping.source, user_id),
        source_document_id=_user_deterministic_uuid(
            "document", clipping.source, user_id
        ),
        source_version_id=_user_deterministic_uuid(
            "version-1", clipping.source, user_id
        ),
    )


def parse_clipping(path: Path) -> Clipping:
    """Markdown 파일 하나를 검증하고 Seed용 클리핑으로 변환한다."""
    text = path.read_text(encoding="utf-8")
    lines = text.splitlines(keepends=True)
    if not lines or lines[0].strip() != "---":
        raise ValueError(f"Frontmatter 시작 구분자가 없습니다: {path}")

    boundary_index = next(
        (index for index, line in enumerate(lines[1:], start=1) if line.strip() == "---"),
        None,
    )
    if boundary_index is None:
        raise ValueError(f"Frontmatter 종료 구분자가 없습니다: {path}")

    frontmatter = _parse_frontmatter(
        [line.rstrip("\r\n") for line in lines[1:boundary_index]]
    )
    content = "".join(lines[boundary_index + 1 :]).lstrip("\r\n")
    title = _as_optional_text(frontmatter.get("title"))
    source = _as_optional_text(frontmatter.get("source"))
    clipped_on = _as_optional_text(frontmatter.get("created"))

    if title is None or source is None or clipped_on is None or not content.strip():
        raise ValueError(f"title, source, created, 본문은 필수입니다: {path}")
    parsed_source = urlparse(source)
    if parsed_source.scheme not in {"http", "https"} or not parsed_source.netloc:
        raise ValueError(f"HTTP(S) Source URL이 아닙니다: {path} ({source})")
    date.fromisoformat(clipped_on)

    content_hash = hashlib.sha256(content.encode("utf-8")).hexdigest()
    source_digest = hashlib.sha256(source.encode("utf-8")).hexdigest()[:16]
    return Clipping(
        path=path,
        title=title,
        source=source,
        author=_as_optional_text(frontmatter.get("author")),
        published_at=_normalize_published_at(frontmatter.get("published")),
        clipped_on=clipped_on,
        description=_as_optional_text(frontmatter.get("description")),
        tags=_as_tags(frontmatter.get("tags")),
        content=content,
        content_hash=content_hash,
        source_event_key=f"dummy-clipping-{source_digest}",
    )


def load_clippings(input_dir: Path) -> list[Clipping]:
    """입력 Directory의 모든 Markdown을 이름순으로 읽고 중복을 검증한다."""
    clippings = [parse_clipping(path) for path in sorted(input_dir.glob("*.md"))]
    if not clippings:
        raise ValueError(f"클리핑 Markdown이 없습니다: {input_dir}")

    sources = [clipping.source for clipping in clippings]
    if len(sources) != len(set(sources)):
        raise ValueError("dummy/clippings 안에 중복 Source URL이 있습니다.")
    return clippings


def _dollar_quote(value: str) -> str:
    """임의 Unicode와 따옴표를 안전하게 보존하는 PostgreSQL Dollar Quote를 만든다."""
    suffix = hashlib.sha256(value.encode("utf-8")).hexdigest()[:12]
    tag = f"seed_{suffix}"
    while f"${tag}$" in value:
        tag = f"{tag}_x"
    return f"${tag}${value}${tag}$"


def _sql_text(value: str | None) -> str:
    """선택 문자열을 PostgreSQL Text Literal로 변환한다."""
    return "NULL" if value is None else _dollar_quote(value)


def _sql_json(value: dict[str, object]) -> str:
    """Dictionary를 UTF-8 JSONB Literal로 변환한다."""
    serialized = json.dumps(value, ensure_ascii=False, separators=(",", ":"), sort_keys=True)
    return f"{_dollar_quote(serialized)}::jsonb"


def _sql_array(values: tuple[str, ...]) -> str:
    """문자열 Tuple을 PostgreSQL text[] Literal로 변환한다."""
    if not values:
        return "'{}'::text[]"
    return f"ARRAY[{', '.join(_dollar_quote(value) for value in values)}]::text[]"


def _render_values(rows: list[tuple[str, ...]]) -> str:
    """여러 SQL Value Row를 읽기 쉬운 VALUES 본문으로 렌더링한다."""
    return ",\n".join(
        "    (\n        " + ",\n        ".join(row) + "\n    )" for row in rows
    )


def render_seed(
    clippings: list[Clipping],
    input_dir: Path,
    user_ids: tuple[str, ...] = SEED_USER_IDS,
) -> str:
    """클리핑 목록을 반복 적용 가능한 PostgreSQL Seed SQL로 렌더링한다."""
    relative_input = input_dir.relative_to(PROJECT_ROOT)
    seed_entries = [
        (user_id, clipping, _seed_identifiers(clipping, user_id))
        for user_id in user_ids
        for clipping in clippings
    ]
    job_ids = ",\n    ".join(
        f"'{identifiers.job_id}'" for _, _, identifiers in seed_entries
    )
    source_version_ids = ",\n    ".join(
        f"'{identifiers.source_version_id}'" for _, _, identifiers in seed_entries
    )
    seed_user_ids = ", ".join(f"'{user_id}'" for user_id in user_ids)

    context_rows: list[tuple[str, ...]] = []
    job_rows: list[tuple[str, ...]] = []
    event_rows: list[tuple[str, ...]] = []
    source_document_rows: list[tuple[str, ...]] = []
    source_version_rows: list[tuple[str, ...]] = []

    for user_id in user_ids:
        context_rows.append(
            (
                f"'{_user_deterministic_uuid('context', user_id, user_id)}'",
                f"'{user_id}'",
                "1",
                "'free'",
                "'ko'",
                "true",
                "'{\"seed\":true,\"source\":\"dummy/clippings\"}'::jsonb",
            )
        )

    for user_id, clipping, identifiers in seed_entries:
        namespace = f"user/{user_id}"
        relative_path = clipping.path.relative_to(PROJECT_ROOT).as_posix()
        job_payload = {
            "content_format": "markdown",
            "seed": True,
            "source_document_id": str(identifiers.source_document_id),
            "source_document_version_id": str(identifiers.source_version_id),
            "source_event_id": clipping.source_event_key,
            "source_event_row_id": str(identifiers.event_id),
        }
        event_payload = {
            "seed": True,
            "source_document_id": str(identifiers.source_document_id),
            "source_document_version_id": str(identifiers.source_version_id),
            "source_filename": relative_path,
        }
        metadata = {"seed": True, "source_filename": relative_path}
        source_metadata = {
            "frontmatter_format": "obsidian_web_clipper",
            "seed": True,
            "source_filename": relative_path,
        }

        job_rows.append(
            (
                f"'{identifiers.job_id}'",
                "'SVC-002'",
                "'personal_wiki_build'",
                f"'{user_id}'",
                _dollar_quote(clipping.source_event_key),
                "'queued'",
                "0",
                _sql_json(job_payload),
                "true",
                f"'{clipping.clipped_on}T00:00:00Z'::timestamptz",
            )
        )
        event_rows.append(
            (
                f"'{identifiers.event_id}'",
                f"'{user_id}'",
                _dollar_quote(clipping.source_event_key),
                "'web_clipping'",
                f"'{identifiers.job_id}'",
                f"'{clipping.clipped_on}T00:00:00Z'::timestamptz",
                _dollar_quote(clipping.source),
                _sql_json(event_payload),
                "'received'",
            )
        )
        source_document_rows.append(
            (
                f"'{identifiers.source_document_id}'",
                f"'{user_id}'",
                f"'{namespace}'",
                "'web_clipping'",
                _dollar_quote(clipping.source),
                "'active'",
                "1",
                f"'{clipping.content_hash}'",
                _sql_json(metadata),
            )
        )
        source_version_rows.append(
            (
                f"'{identifiers.source_version_id}'",
                f"'{identifiers.source_document_id}'",
                f"'{namespace}'",
                f"'{identifiers.event_id}'",
                "1",
                _dollar_quote(clipping.title),
                _sql_text(clipping.author),
                (
                    "NULL"
                    if clipping.published_at is None
                    else f"'{clipping.published_at}'::timestamptz"
                ),
                f"'{clipping.clipped_on}'::date",
                _sql_text(clipping.description),
                _sql_array(clipping.tags),
                _dollar_quote(clipping.content),
                "'markdown'",
                f"'{clipping.content_hash}'",
                "NULL",
                _sql_json(source_metadata),
            )
        )

    return f"""-- 이 파일은 scripts/generate_web_clipping_seed.py가 {relative_input}에서 생성한다.
-- 직접 수정하지 말고 원본 Markdown을 바꾼 뒤 Generator를 다시 실행한다.

\\set ON_ERROR_STOP on

BEGIN;

SET LOCAL app.access_scope = 'system';

DELETE FROM agent.agent_job_attempts
WHERE job_id IN (
    {job_ids}
);

-- 같은 원본으로 이전에 생성한 LLM Wiki 결과 중 Citation이 참조하지 않는 문서를 제거한다.
DELETE FROM agent.wiki_documents AS document
WHERE document.id IN (
    SELECT version.document_id
    FROM agent.wiki_document_versions AS version
    WHERE version.created_by_job_id IN (
        {job_ids}
    )
    UNION
    SELECT version.document_id
    FROM agent.wiki_document_versions AS version
    JOIN agent.wiki_document_sources AS source_link
      ON source_link.wiki_document_version_id = version.id
    WHERE source_link.source_document_version_id IN (
        {source_version_ids}
    )
)
AND NOT EXISTS (
    SELECT 1
    FROM agent.wiki_document_versions AS version
    JOIN agent.citations AS citation
      ON citation.document_version_id = version.id
    WHERE version.document_id = document.id
)
AND NOT EXISTS (
    SELECT 1
    FROM agent.wiki_document_versions AS version
    JOIN agent.wiki_chunks AS chunk
      ON chunk.document_version_id = version.id
    JOIN agent.citations AS citation
      ON citation.chunk_id = chunk.id
    WHERE version.document_id = document.id
)
-- 관심 키워드 근거(INT-011)가 문서를 참조하면 남긴다. Citation과 같은 이유로,
-- Seed 재적용이 이미 만들어진 결과를 끊어 버리면 안 된다. 이 가드가 없으면
-- 관심사를 한 번이라도 계산한 DB에서 Seed가 외래키 위반으로 실패한다.
AND NOT EXISTS (
    SELECT 1
    FROM agent.interest_evidence AS evidence
    WHERE evidence.document_id = document.id
);

DELETE FROM agent.user_interest_profiles
WHERE user_id IN ({seed_user_ids});

DELETE FROM agent.wiki_versions
WHERE user_id IN ({seed_user_ids});

INSERT INTO agent.user_context_snapshots (
    id,
    user_id,
    context_version,
    plan,
    preferred_language,
    personalization_enabled,
    attributes
) VALUES
{_render_values(context_rows)}
ON CONFLICT (id) DO UPDATE SET
    plan = EXCLUDED.plan,
    preferred_language = EXCLUDED.preferred_language,
    personalization_enabled = EXCLUDED.personalization_enabled,
    attributes = EXCLUDED.attributes;

INSERT INTO agent.agent_jobs (
    id,
    feature_id,
    job_type,
    user_id,
    idempotency_key,
    status,
    progress,
    payload,
    retryable,
    scheduled_at
) VALUES
{_render_values(job_rows)}
ON CONFLICT (id) DO UPDATE SET
    status = 'queued',
    progress = 0,
    payload = EXCLUDED.payload,
    result = NULL,
    error_code = NULL,
    error_message = NULL,
    retryable = true,
    attempt_count = 0,
    queue_message_id = NULL,
    locked_at = NULL,
    locked_by = NULL,
    lease_expires_at = NULL,
    started_at = NULL,
    completed_at = NULL,
    scheduled_at = EXCLUDED.scheduled_at,
    updated_at = clock_timestamp();

INSERT INTO agent.wiki_source_events (
    id,
    user_id,
    source_event_id,
    source_type,
    job_id,
    occurred_at,
    source_url,
    payload,
    status
) VALUES
{_render_values(event_rows)}
ON CONFLICT (id) DO UPDATE SET
    job_id = EXCLUDED.job_id,
    occurred_at = EXCLUDED.occurred_at,
    source_url = EXCLUDED.source_url,
    payload = EXCLUDED.payload,
    status = 'received',
    retry_count = 0,
    error_code = NULL,
    error_message = NULL,
    processed_at = NULL,
    updated_at = clock_timestamp();

INSERT INTO agent.user_source_documents (
    id,
    user_id,
    namespace_key,
    source_type,
    canonical_url,
    status,
    current_version,
    content_hash,
    metadata
) VALUES
{_render_values(source_document_rows)}
ON CONFLICT (id) DO UPDATE SET
    canonical_url = EXCLUDED.canonical_url,
    status = 'active',
    current_version = 1,
    content_hash = EXCLUDED.content_hash,
    metadata = EXCLUDED.metadata,
    deleted_at = NULL,
    updated_at = clock_timestamp();

INSERT INTO agent.user_source_document_versions (
    id,
    source_document_id,
    namespace_key,
    source_event_id,
    version,
    title,
    author,
    published_at,
    clipped_on,
    description,
    tags,
    raw_content,
    content_format,
    content_hash,
    object_uri,
    source_metadata
) VALUES
{_render_values(source_version_rows)}
ON CONFLICT (id) DO UPDATE SET
    source_event_id = EXCLUDED.source_event_id,
    title = EXCLUDED.title,
    author = EXCLUDED.author,
    published_at = EXCLUDED.published_at,
    clipped_on = EXCLUDED.clipped_on,
    description = EXCLUDED.description,
    tags = EXCLUDED.tags,
    raw_content = EXCLUDED.raw_content,
    content_format = EXCLUDED.content_format,
    content_hash = EXCLUDED.content_hash,
    object_uri = EXCLUDED.object_uri,
    source_metadata = EXCLUDED.source_metadata;

COMMIT;
"""


def _build_parser() -> argparse.ArgumentParser:
    """Generator CLI Argument Parser를 구성한다."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--input-dir", type=Path, default=DEFAULT_INPUT_DIR)
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT_PATH)
    parser.add_argument(
        "--check",
        action="store_true",
        help="생성 결과가 기존 출력 파일과 같은지만 확인한다.",
    )
    return parser


def main() -> int:
    """클리핑을 읽어 Seed를 생성하거나 최신 상태인지 검사한다."""
    args = _build_parser().parse_args()
    clippings = load_clippings(args.input_dir.resolve())
    rendered = render_seed(clippings, args.input_dir.resolve())

    if args.check:
        if not args.output.exists() or args.output.read_text(encoding="utf-8") != rendered:
            print(f"웹 클리핑 Seed가 최신 상태가 아닙니다: {args.output}", file=sys.stderr)
            return 1
        print(f"웹 클리핑 Seed 확인 완료: {len(clippings)}건")
        return 0

    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(rendered, encoding="utf-8")
    print(f"웹 클리핑 Seed 생성 완료: {len(clippings)}건 -> {args.output}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
