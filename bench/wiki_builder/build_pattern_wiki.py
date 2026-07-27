"""llm-wiki.md 패턴을 그대로 수행하는 3번 비교군 생성기.

nashsu/llm_wiki 저장소는 두 가지를 제공한다. 하나는 데스크톱 앱(2번 비교군)이고,
다른 하나는 `llm-wiki.md`에 적힌 패턴 문서다. 패턴 문서는 "당신의 LLM 에이전트에
복사해 넣으라"고 명시하며, 앱의 고정 파이프라인 없이 에이전트가 직접 위키를
쌓는 방식을 설명한다. 이 스크립트가 그 방식을 재현한다.

출력은 앱과 같은 Vault 구조(`entities/`·`concepts/`·`sources/`·`index.md`·`log.md`)로
쓴다. 형식이 같아야 compare_obsidian.py의 파서로 세 결과물을 같은 기준에서
비교할 수 있기 때문이다. 규칙은 앱이 쓰는 schema/config.md의 페이지 템플릿과
명명·인용 규칙을 따른다.
"""

from __future__ import annotations

import argparse
import json
import re
import sys
import time
from collections import OrderedDict
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

PROJECT_ROOT = Path(__file__).resolve().parents[2]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from dotenv import load_dotenv

# OPENAI_API_KEY를 .env에서 읽는다(앱 진입점과 같은 방식).
load_dotenv(PROJECT_ROOT / ".env")

from agent.llm.api import complete_with_usage

ROOT = Path(__file__).resolve().parent

_ENTITY_TAGS = (
    "person",
    "organization",
    "project",
    "product",
    "event",
    "place",
    "other",
)
_CONCEPT_TAGS = (
    "theory",
    "method",
    "field",
    "phenomenon",
    "standard",
    "term",
    "other",
)

# llm-wiki.md의 패턴(누적되는 위키를 LLM이 유지)과 schema/config.md의 페이지
# 규칙을 하나의 지시로 합친 시스템 프롬프트.
_SYSTEM_PROMPT = f"""너는 개인 지식 Wiki를 점진적으로 쌓아 유지하는 LLM 사서다.

원문을 그때그때 검색하는 방식이 아니라, 읽은 내용을 기존 Wiki에 통합해 계속
축적되는 지식으로 만든다. 이미 있는 페이지는 새로 만들지 말고 그 페이지에 내용을
더한다. 원문에 있는 사실만 사용하고 없는 사실을 지어내지 마라.

[페이지 판단]
- entity: 사람, 조직, 프로젝트, 제품, 사건, 장소처럼 고유하게 식별되는 대상.
  tags는 {", ".join(_ENTITY_TAGS)} 중 하나.
- concept: 이론, 방법, 분야, 현상, 표준, 용어처럼 재사용 가능한 지식.
  tags는 {", ".join(_CONCEPT_TAGS)} 중 하나.
- 여러 원문을 관통하는 사건·분쟁·정책 흐름은 개별 개체로 흩지 말고 하나의
  concept 페이지로 묶는다.
- 이름은 원문 언어를 그대로 보존하고 번역하지 마라. 번역명·약어·다른 표기는
  aliases에 넣는다.
- 기존 페이지 목록에 같은 대상이 있으면 그 slug를 그대로 쓴다.

[연결]
- related_entities와 related_concepts에는 원문이 실제로 뒷받침하는 관계만 넣는다.
- 같은 원문에 함께 등장했다는 이유만으로 연결하지 마라.
- 연결 대상은 이번 응답에 선언했거나 기존 목록에 있는 이름만 사용한다.

[인용]
- mentions에는 원문에서 글자 그대로 복사한 짧은 문장만 넣는다. 요약·의역·번역 금지.

slug는 소문자와 하이픈만 사용한다(원문 언어 문자는 그대로 두고 공백만 하이픈으로).

반드시 아래 JSON 객체만 출력하고 코드펜스를 붙이지 마라.

{{
  "summary": "원문 요약 2~4문장",
  "key_points": ["핵심 항목"],
  "entities": [{{"name":"","slug":"","tags":"other","aliases":[],"description":"",
    "related_entities":[],"related_concepts":[],"mentions":[]}}],
  "concepts": [{{"name":"","slug":"","tags":"other","aliases":[],"definition":"",
    "key_characteristics":[],"applications":[],"related_concepts":[],
    "related_entities":[],"mentions":[]}}]
}}
"""


def _slugify(value: str) -> str:
    """페이지 파일명에 쓸 slug를 만든다(원문 언어 문자는 보존한다)."""
    text = str(value or "").strip().casefold()
    text = re.sub(r"[\\/:*?\"<>|]+", "", text)
    text = re.sub(r"\s+", "-", text)
    return text.strip("-")


def _frontmatter_block(text: str) -> tuple[dict[str, Any], str]:
    """클리핑 원문의 앞머리 YAML을 최소 규칙으로 읽고 본문과 분리한다."""
    if not text.startswith("---"):
        return {}, text
    parts = text.split("---", 2)
    if len(parts) < 3:
        return {}, text
    meta: dict[str, Any] = {}
    current: str | None = None
    for line in parts[1].splitlines():
        if not line.strip():
            continue
        item = re.match(r"^\s*-\s+(.*)$", line)
        if item and current:
            values = meta.setdefault(current, [])
            if isinstance(values, list):
                values.append(item.group(1).strip().strip('"').strip("'"))
            continue
        pair = re.match(r"^([A-Za-z_][\w]*):\s*(.*)$", line)
        if pair:
            current = pair.group(1)
            raw = pair.group(2).strip()
            if raw.startswith("[") and raw.endswith("]"):
                meta[current] = [
                    piece.strip().strip('"').strip("'")
                    for piece in raw[1:-1].split(",")
                    if piece.strip()
                ]
            else:
                meta[current] = raw.strip('"').strip("'") if raw else []
    return meta, parts[2]


def load_clippings(directory: Path) -> list[dict[str, Any]]:
    """세 비교군의 공통 입력인 원본 클리핑을 읽는다."""
    cases: list[dict[str, Any]] = []
    for path in sorted(directory.glob("*.md")):
        meta, body = _frontmatter_block(path.read_text(encoding="utf-8"))
        tags = meta.get("tags")
        cases.append(
            {
                "slug": _slugify(path.stem),
                "title": str(meta.get("title") or path.stem),
                "tags": tags if isinstance(tags, list) else ([tags] if tags else []),
                "content": body.strip(),
            }
        )
    return cases


def _parse_response(raw: str) -> dict[str, Any]:
    """LLM 응답에서 JSON 객체만 안전하게 추출한다."""
    text = raw.strip()
    if text.startswith("```"):
        text = re.sub(r"^```[a-zA-Z]*\n|\n```$", "", text).strip()
    start, end = text.find("{"), text.rfind("}")
    if start < 0 or end <= start:
        raise ValueError("JSON 객체를 찾지 못했습니다.")
    return json.loads(text[start : end + 1])


class Vault:
    """패턴대로 누적되는 Wiki Vault 상태를 담는다."""

    def __init__(self) -> None:
        """빈 Vault를 만든다."""
        self.pages: OrderedDict[str, dict[str, Any]] = OrderedDict()
        self.sources: list[dict[str, Any]] = []
        self.log: list[str] = []

    def existing_listing(self) -> str:
        """다음 원문 처리에 넘길 기존 페이지 목록을 만든다."""
        if not self.pages:
            return "(없음)"
        lines = []
        for key, page in self.pages.items():
            kind, slug = key.split("/", 1)
            alias = (
                f" [aliases={', '.join(page['aliases'])}]" if page["aliases"] else ""
            )
            lines.append(f"- {kind}/{slug}: {page['name']} [tags={page['tags']}]{alias}")
        return "\n".join(lines)

    def merge(self, kind: str, item: dict[str, Any], source_slug: str) -> None:
        """추출 결과 한 건을 기존 페이지에 병합하거나 새로 만든다."""
        name = str(item.get("name") or "").strip()
        if not name:
            return
        slug = _slugify(item.get("slug") or name)
        if not slug:
            return
        key = f"{kind}/{slug}"
        allowed = _ENTITY_TAGS if kind == "entities" else _CONCEPT_TAGS
        tags = str(item.get("tags") or "other")
        page = self.pages.get(key)
        if page is None:
            page = {
                "name": name,
                "kind": kind,
                "tags": tags if tags in allowed else "other",
                "aliases": [],
                "body": {},
                "related_entities": [],
                "related_concepts": [],
                "mentions": [],
                "sources": [],
            }
            self.pages[key] = page
        # 병합 규칙: sources·aliases·mentions는 덮어쓰지 않고 덧붙인다.
        for alias in item.get("aliases") or []:
            alias_text = str(alias).strip()
            if alias_text and alias_text not in page["aliases"]:
                page["aliases"].append(alias_text)
        for field in ("related_entities", "related_concepts"):
            for link in item.get(field) or []:
                link_text = str(link).strip()
                if link_text and link_text not in page[field]:
                    page[field].append(link_text)
        for mention in item.get("mentions") or []:
            quote = str(mention).strip()
            if quote:
                page["mentions"].append((quote, source_slug))
        if source_slug not in page["sources"]:
            page["sources"].append(source_slug)
        for field in ("description", "definition"):
            value = str(item.get(field) or "").strip()
            if value and not page["body"].get(field):
                page["body"][field] = value
        for field in ("key_characteristics", "applications"):
            for value in item.get(field) or []:
                text = str(value).strip()
                bucket = page["body"].setdefault(field, [])
                if text and text not in bucket:
                    bucket.append(text)


def _render_page(slug: str, page: dict[str, Any], today: str) -> str:
    """schema/config.md 템플릿에 맞춰 페이지 Markdown을 만든다."""
    lines = ["---", f"type: {'entity' if page['kind'] == 'entities' else 'concept'}"]
    lines.append(f"created: {today}")
    lines.append("sources:")
    for source in page["sources"]:
        lines.append(f'  - "[[sources/{source}]]"')
    lines.append("tags:")
    lines.append(f'  - "{page["tags"]}"')
    if page["aliases"]:
        lines.append("aliases:")
        for alias in page["aliases"]:
            lines.append(f'  - "{alias}"')
    lines.append("---")
    lines.append("")
    if page["kind"] == "entities":
        lines.append("## Description")
        lines.append(page["body"].get("description", ""))
    else:
        lines.append("## Definition")
        lines.append(page["body"].get("definition", ""))
        if page["body"].get("key_characteristics"):
            lines.append("")
            lines.append("## Key Characteristics")
            lines.extend(f"- {item}" for item in page["body"]["key_characteristics"])
        if page["body"].get("applications"):
            lines.append("")
            lines.append("## Applications")
            lines.extend(f"- {item}" for item in page["body"]["applications"])
    if page["related_entities"]:
        lines.append("")
        lines.append("## Related Entities")
        lines.extend(
            f"- [[entities/{_slugify(name)}|{name}]]"
            for name in page["related_entities"]
        )
    if page["related_concepts"]:
        lines.append("")
        lines.append("## Related Concepts")
        lines.extend(
            f"- [[concepts/{_slugify(name)}|{name}]]"
            for name in page["related_concepts"]
        )
    if page["mentions"]:
        lines.append("")
        lines.append("## Mentions in Source")
        lines.extend(
            f'- "{quote}" — [[sources/{source}]]' for quote, source in page["mentions"]
        )
    return "\n".join(lines) + "\n"


def _render_source(entry: dict[str, Any], today: str) -> str:
    """원문 요약 페이지 Markdown을 만든다."""
    lines = ["---", "type: source", f"created: {today}", "tags:"]
    for tag in entry["tags"] or ["clippings"]:
        lines.append(f'  - "{tag}"')
    lines.append("---")
    lines.append("")
    lines.append(f"# {entry['title']}")
    lines.append("")
    lines.append("## Summary")
    lines.append(entry["summary"])
    if entry["key_points"]:
        lines.append("")
        lines.append("## Key Points")
        lines.extend(f"- {point}" for point in entry["key_points"])
    if entry["pages"]:
        lines.append("")
        lines.append("## Mentioned Pages")
        lines.extend(f"- [[{page}]]" for page in entry["pages"])
    return "\n".join(lines) + "\n"


def write_vault(vault: Vault, target: Path, today: str) -> None:
    """누적된 Vault 상태를 앱과 같은 디렉터리 구조로 기록한다."""
    for folder in ("entities", "concepts", "sources"):
        directory = target / folder
        directory.mkdir(parents=True, exist_ok=True)
        for path in directory.glob("*.md"):
            path.unlink()
    for key, page in vault.pages.items():
        kind, slug = key.split("/", 1)
        (target / kind / f"{slug}.md").write_text(
            _render_page(slug, page, today), encoding="utf-8"
        )
    for entry in vault.sources:
        (target / "sources" / f"{entry['slug']}.md").write_text(
            _render_source(entry, today), encoding="utf-8"
        )
    index = ["# Wiki Index", "", "> llm-wiki.md 패턴으로 생성한 비교군", ""]
    for kind, title in (("entities", "Entities"), ("concepts", "Concepts")):
        index.append(f"## {title}")
        index.append("")
        for key, page in vault.pages.items():
            if page["kind"] != kind:
                continue
            slug = key.split("/", 1)[1]
            alias = (
                f" `aliases: {', '.join(page['aliases'])}`" if page["aliases"] else ""
            )
            index.append(f"- [[{kind}/{slug}|{page['name']}]]{alias}")
        index.append("")
    (target / "index.md").write_text("\n".join(index) + "\n", encoding="utf-8")
    (target / "log.md").write_text(
        "# Wiki Operation Log\n\n" + "\n".join(vault.log) + "\n", encoding="utf-8"
    )


def _args() -> argparse.Namespace:
    """실행 옵션을 파싱한다."""
    parser = argparse.ArgumentParser(description="llm-wiki.md 패턴 비교군 생성")
    parser.add_argument("--clippings", required=True, help="공통 원본 클리핑 경로")
    parser.add_argument(
        "--out",
        default=str(ROOT / "pattern_vault"),
        help="생성할 Vault 경로",
    )
    parser.add_argument("--model", default="gpt-4o-mini")
    parser.add_argument("--input-cost-per-million", type=float, required=True)
    parser.add_argument("--output-cost-per-million", type=float, required=True)
    return parser.parse_args()


def main() -> None:
    """원본을 순서대로 삼켜 누적 Wiki를 만들고 결과를 보고한다."""
    args = _args()
    cases = load_clippings(Path(args.clippings))
    vault = Vault()
    usage = {"input": 0, "output": 0}
    today = datetime.now(UTC).date().isoformat()
    rows: list[dict[str, Any]] = []

    for case in cases:
        started = time.perf_counter()
        user_prompt = (
            f"[기존 Wiki 페이지 목록]\n{vault.existing_listing()}\n\n"
            f"[원문 제목]\n{case['title']}\n\n"
            f"[원문 태그]\n{', '.join(case['tags']) or '(없음)'}\n\n"
            f"[원문 본문]\n{case['content']}"
        )
        error = ""
        payload: dict[str, Any] = {}
        try:
            completion = complete_with_usage(
                _SYSTEM_PROMPT, user_prompt, model=args.model, temperature=0
            )
            usage["input"] += completion.input_tokens
            usage["output"] += completion.output_tokens
            payload = _parse_response(completion.text)
        except Exception as exc:
            error = f"{type(exc).__name__}: {exc}"

        pages: list[str] = []
        for kind, field in (("entities", "entities"), ("concepts", "concepts")):
            for item in payload.get(field) or []:
                vault.merge(kind, item, case["slug"])
                slug = _slugify(item.get("slug") or item.get("name") or "")
                if slug:
                    pages.append(f"{kind}/{slug}")
        vault.sources.append(
            {
                "slug": case["slug"],
                "title": case["title"],
                "tags": case["tags"],
                "summary": str(payload.get("summary") or ""),
                "key_points": [str(point) for point in payload.get("key_points") or []],
                "pages": pages,
            }
        )
        elapsed = time.perf_counter() - started
        vault.log.append(
            f"## [{datetime.now(UTC).strftime('%Y-%m-%d %H:%M')}] ingest | "
            f"{case['title']} · {elapsed:.0f}s · {args.model}"
        )
        rows.append(
            {
                "id": case["slug"],
                "entities": len(payload.get("entities") or []),
                "concepts": len(payload.get("concepts") or []),
                "latency": elapsed,
                "error": error,
            }
        )

    target = Path(args.out)
    target.mkdir(parents=True, exist_ok=True)
    write_vault(vault, target, today)

    cost = (
        usage["input"] * args.input_cost_per_million
        + usage["output"] * args.output_cost_per_million
    ) / 1_000_000
    entity_pages = sum(1 for page in vault.pages.values() if page["kind"] == "entities")
    concept_pages = len(vault.pages) - entity_pages
    print(f"Vault: {target}")
    print(f"- entity 페이지: {entity_pages} / concept 페이지: {concept_pages}")
    print(f"- 입력 토큰 {usage['input']} / 출력 토큰 {usage['output']}")
    print(f"- 예상 비용: ${cost:.6f}")
    for row in rows:
        status = row["error"] or "ok"
        print(
            f"  {row['id'][:40]:<42} E{row['entities']:<3} C{row['concepts']:<3} "
            f"{row['latency']:.1f}s  {status}"
        )


if __name__ == "__main__":
    main()
