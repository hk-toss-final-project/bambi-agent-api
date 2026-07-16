"""사용자 URL 목록에서 로컬 PostgreSQL 개발 Seed SQL을 생성한다."""

from __future__ import annotations

import argparse
import hashlib
import json
import sys
import uuid
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT))

from scripts.user_url_file import load_user_urls

DEFAULT_INPUT_PATH = PROJECT_ROOT / "dummy" / "urls" / "url.txt"
DEFAULT_OUTPUT_PATH = PROJECT_ROOT / "database" / "seeds" / "0004_dev_user_urls.sql"
SEED_NAMESPACE = uuid.UUID("a5de28b9-5f0e-40fb-96fa-64780430ccde")
MOCK_USER_ID = "mock-clipping-user"
MOCK_NAMESPACE = f"user/{MOCK_USER_ID}"


def _deterministic_uuid(kind: str, url: str) -> uuid.UUID:
    """URL과 Entity 종류로 재생성 가능한 UUID를 만든다."""
    return uuid.uuid5(SEED_NAMESPACE, f"{kind}:{url}")


def _source_event_id(url: str) -> str:
    """실제 URL 수집 스크립트와 같은 멱등 이벤트 식별자를 만든다."""
    return f"user-url-{hashlib.sha256(url.encode('utf-8')).hexdigest()[:16]}"


def _dollar_quote(value: str) -> str:
    """임의 URL과 JSON을 안전하게 보존하는 PostgreSQL Dollar Quote를 만든다."""
    suffix = hashlib.sha256(value.encode("utf-8")).hexdigest()[:12]
    tag = f"seed_{suffix}"
    while f"${tag}$" in value:
        tag = f"{tag}_x"
    return f"${tag}${value}${tag}$"


def _sql_json(value: dict[str, object]) -> str:
    """Dictionary를 UTF-8 JSONB Literal로 변환한다."""
    serialized = json.dumps(
        value,
        ensure_ascii=False,
        separators=(",", ":"),
        sort_keys=True,
    )
    return f"{_dollar_quote(serialized)}::jsonb"


def _render_values(rows: list[tuple[str, ...]]) -> str:
    """여러 SQL Value Row를 읽기 쉬운 VALUES 본문으로 렌더링한다."""
    return ",\n".join(
        "    (\n        " + ",\n        ".join(row) + "\n    )" for row in rows
    )


def render_seed(urls: list[str], input_path: Path) -> str:
    """URL 목록을 기존 처리 결과를 보존하는 멱등 PostgreSQL Seed로 렌더링한다."""
    relative_input = input_path.relative_to(PROJECT_ROOT).as_posix()
    event_rows: list[tuple[str, ...]] = []
    document_rows: list[tuple[str, ...]] = []

    for url in urls:
        source_event_id = _source_event_id(url)
        event_rows.append(
            (
                f"'{_deterministic_uuid('event', url)}'",
                f"'{MOCK_USER_ID}'",
                _dollar_quote(source_event_id),
                "'url'",
                "clock_timestamp()",
                _dollar_quote(url),
                _sql_json(
                    {"seed": True, "source_filename": relative_input, "url": url}
                ),
                "'received'",
            )
        )
        document_rows.append(
            (
                f"'{_deterministic_uuid('document', url)}'",
                f"'{MOCK_USER_ID}'",
                f"'{MOCK_NAMESPACE}'",
                "'url'",
                _dollar_quote(url),
                "'active'",
                "1",
                f"'{hashlib.sha256(url.encode('utf-8')).hexdigest()}'",
                _sql_json(
                    {
                        "registered_by": "development-seed",
                        "seed": True,
                        "source_filename": relative_input,
                    }
                ),
            )
        )

    return f"""-- 이 파일은 scripts/generate_user_url_seed.py가 {relative_input}에서 생성한다.
-- 직접 수정하지 말고 원본 URL 목록을 바꾼 뒤 Generator를 다시 실행한다.

\\set ON_ERROR_STOP on

BEGIN;

SET LOCAL app.access_scope = 'system';

INSERT INTO agent.wiki_source_events AS event (
    id,
    user_id,
    source_event_id,
    source_type,
    occurred_at,
    source_url,
    payload,
    status
) VALUES
{_render_values(event_rows)}
ON CONFLICT (user_id, source_event_id) DO UPDATE SET
    source_url = EXCLUDED.source_url,
    payload = event.payload || EXCLUDED.payload,
    updated_at = clock_timestamp();

INSERT INTO agent.user_source_documents AS document (
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
{_render_values(document_rows)}
ON CONFLICT (namespace_key, canonical_url)
WHERE canonical_url IS NOT NULL AND deleted_at IS NULL
DO UPDATE SET
    metadata = document.metadata || EXCLUDED.metadata,
    updated_at = clock_timestamp();

COMMIT;
"""


def _build_parser() -> argparse.ArgumentParser:
    """Generator CLI Argument Parser를 구성한다."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--input", type=Path, default=DEFAULT_INPUT_PATH)
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT_PATH)
    parser.add_argument(
        "--check",
        action="store_true",
        help="생성 결과가 기존 출력 파일과 같은지만 확인한다.",
    )
    return parser


def main() -> int:
    """URL 목록을 읽어 Seed를 생성하거나 최신 상태인지 검사한다."""
    args = _build_parser().parse_args()
    input_path = args.input.resolve()
    urls = load_user_urls(input_path)
    rendered = render_seed(urls, input_path)

    if args.check:
        if not args.output.exists() or args.output.read_text(encoding="utf-8") != rendered:
            print(f"사용자 URL Seed가 최신 상태가 아닙니다: {args.output}", file=sys.stderr)
            return 1
        print(f"사용자 URL Seed 확인 완료: {len(urls)}건")
        return 0

    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(rendered, encoding="utf-8")
    print(f"사용자 URL Seed 생성 완료: {len(urls)}건 -> {args.output}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
