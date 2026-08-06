"""웹 클리퍼가 만든 Markdown 파일을 Agent API에 개인 Wiki 원본으로 등록한다.

웹 클리퍼(Obsidian Web Clipper 등)는 페이지를 YAML Frontmatter + Markdown 파일로
저장한다. 실제 서비스에서는 Service가 그 내용을 Agent API로 넘기지만, 연동 전에는
이 스크립트로 같은 요청을 보내 개인 Wiki 경로를 검증할 수 있다.

등록하면 원본 저장 → 위키 빌드 Job 등록까지 진행되고, Worker가 Entity·Concept
문서를 만든다. 그 뒤 리포트를 생성하면 근거에 `P` 참조로 인용된다.

실행:
    uv run python scripts/upload_clipping.py "클리핑.md"
    uv run python scripts/upload_clipping.py "클리핑.md" --user user-1 --dry-run
"""

from __future__ import annotations

import argparse
import json
import os
import sys
import uuid
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from dotenv import load_dotenv

load_dotenv()

import httpx

DEFAULT_BASE_URL = "http://34.64.53.250:8000/internal/v1"
DEFAULT_USER_ID = "mock-clipping-user"


def parse_clipping(path: Path) -> dict[str, object]:
    """클리핑 Markdown을 Frontmatter와 본문으로 나눈다.

    YAML 라이브러리를 쓰지 않는다 — 클리퍼 Frontmatter는 `key: value`와 `- item`
    두 형태뿐이라 의존성을 늘릴 이유가 없다.

    Args:
        path: 클리핑 Markdown 파일 경로

    Returns:
        Frontmatter 필드와 `content`(본문)를 담은 사전
    """
    raw = path.read_text(encoding="utf-8")
    if not raw.startswith("---"):
        return {"title": path.stem, "content": raw}

    _, front, body = raw.split("---", 2)
    fields: dict[str, object] = {}
    current_list_key: str | None = None
    for line in front.splitlines():
        stripped = line.strip()
        if not stripped:
            continue
        if stripped.startswith("- ") and current_list_key:
            fields.setdefault(current_list_key, [])
            values = fields[current_list_key]
            assert isinstance(values, list)
            values.append(stripped[2:].strip().strip('"'))
            continue
        if ":" not in stripped:
            continue
        key, _, value = stripped.partition(":")
        key = key.strip()
        value = value.strip().strip('"')
        if value:
            fields[key] = value
            current_list_key = None
        else:
            # 값이 비면 다음 줄들이 목록이거나 그냥 빈 필드다.
            current_list_key = key
    fields["content"] = body.strip()
    return fields


def build_request(fields: dict[str, object], *, path: Path) -> dict[str, object]:
    """클리핑 필드를 Agent API 요청 본문으로 만든다."""
    source = str(fields.get("source") or "").strip()
    if not source:
        raise SystemExit(f"source URL이 없어 등록할 수 없습니다: {path.name}")
    payload: dict[str, object] = {
        # 같은 파일을 다시 올려도 새 원본으로 들어가도록 매번 새 ID를 쓴다.
        # 멱등 재시도를 검증하려면 이 값을 고정하면 된다.
        "source_event_id": f"clip-{uuid.uuid4().hex[:16]}",
        "source": source,
        "title": str(fields.get("title") or path.stem),
        "content": str(fields.get("content") or ""),
    }
    for key in ("author", "description"):
        value = str(fields.get(key) or "").strip()
        if value:
            payload[key] = value
    created = str(fields.get("created") or "").strip()
    if created:
        payload["created"] = created
    tags = fields.get("tags")
    if isinstance(tags, list) and tags:
        payload["tags"] = tags
    return payload


def main() -> int:
    """클리핑 파일을 읽어 Agent API에 등록한다."""
    parser = argparse.ArgumentParser(description="클리핑 Markdown 등록")
    parser.add_argument("path", help="클리핑 Markdown 파일 경로")
    parser.add_argument("--user", default=DEFAULT_USER_ID, help="대상 사용자 ID")
    parser.add_argument("--base-url", default=DEFAULT_BASE_URL, help="Agent API 주소")
    parser.add_argument(
        "--dry-run", action="store_true", help="보낼 내용만 출력하고 끝낸다"
    )
    args = parser.parse_args()

    path = Path(args.path)
    if not path.is_file():
        raise SystemExit(f"파일을 찾을 수 없습니다: {path}")

    fields = parse_clipping(path)
    payload = build_request(fields, path=path)

    print(f"파일: {path.name}")
    print(f"  제목: {payload['title']}")
    print(f"  출처: {payload['source']}")
    print(f"  본문: {len(str(payload['content'])):,}자")
    if payload.get("tags"):
        print(f"  태그: {payload['tags']}")

    if args.dry_run:
        print("\n[미리보기] 실제로 보내지 않았습니다.")
        print(json.dumps(payload, ensure_ascii=False, indent=2)[:600])
        return 0

    token = os.environ.get("AGENT_INTERNAL_TOKEN", "")
    if not token:
        raise SystemExit("AGENT_INTERNAL_TOKEN이 필요합니다.")

    response = httpx.post(
        f"{args.base_url}/users/{args.user}/wiki-sources/clippings",
        json=payload,
        headers={"Authorization": f"Bearer {token}"},
        timeout=60.0,
    )
    print(f"\nHTTP {response.status_code}")
    print(response.text[:500])
    return 0 if response.status_code < 400 else 1


if __name__ == "__main__":
    raise SystemExit(main())
