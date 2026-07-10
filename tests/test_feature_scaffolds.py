"""전체 명세 기능과 생성된 함수 스캐폴드의 정합성을 검증한다."""

import ast
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
FEATURE_SPEC = ROOT / "docs" / "agent-api-feature-spec.md"
MVP_SPEC = ROOT / "docs" / "agent-api-mvp-scope.md"
SECTION_PATTERN = re.compile(r"^## (\d+)\.")
TABLE_ID_PATTERN = re.compile(r"^\| ([A-Z][A-Z0-9-]+) \|")
FUNCTION_PATTERN = re.compile(r"^[a-z][a-z0-9]*_\d{3}$")
KOREAN_PATTERN = re.compile(r"[가-힣]")


def read_runtime_feature_ids() -> set[str]:
    """전체 명세의 실제 기능 영역인 1~43절에서 기능 ID를 읽는다."""
    section = 0
    feature_ids: set[str] = set()
    for line in FEATURE_SPEC.read_text(encoding="utf-8").splitlines():
        if match := SECTION_PATTERN.match(line):
            section = int(match.group(1))
            continue
        if section > 43:
            continue
        if (match := TABLE_ID_PATTERN.match(line)) and match.group(1) != "ID":
            feature_ids.add(match.group(1))
    return feature_ids


def read_mvp_feature_ids() -> set[str]:
    """MVP 범위 문서에서 구현 대상으로 지정된 기능 ID를 읽는다."""
    return {
        match.group(1)
        for line in MVP_SPEC.read_text(encoding="utf-8").splitlines()
        if (match := TABLE_ID_PATTERN.match(line))
        if match.group(1) != "ID"
    }


def discover_feature_functions() -> dict[
    str, tuple[Path, ast.AsyncFunctionDef, list[str]]
]:
    """프로젝트에서 기능 ID 형식의 비동기 함수와 원본 위치를 찾는다."""
    discovered: dict[str, tuple[Path, ast.AsyncFunctionDef, list[str]]] = {}
    source_roots = (
        ROOT / "app",
        ROOT / "agent",
        ROOT / "domain",
        ROOT / "infrastructure",
        ROOT / "workers",
        ROOT / "scheduler",
        ROOT / "mcp_server",
        ROOT / "shared",
    )
    for source_root in source_roots:
        for path in source_root.rglob("*.py"):
            source = path.read_text(encoding="utf-8")
            lines = source.splitlines()
            tree = ast.parse(source, filename=str(path))
            for node in ast.walk(tree):
                if isinstance(node, ast.AsyncFunctionDef) and FUNCTION_PATTERN.match(
                    node.name
                ):
                    feature_id = node.name.upper().replace("_", "-")
                    if feature_id in discovered:
                        raise AssertionError(f"중복 기능 함수: {feature_id}")
                    discovered[feature_id] = (path, node, lines)
    return discovered


def is_not_implemented_stub(node: ast.AsyncFunctionDef) -> bool:
    """함수 본문이 NotImplementedError만 발생시키는 스텁인지 확인한다."""
    statement = node.body[-1]
    return (
        isinstance(statement, ast.Raise)
        and isinstance(statement.exc, ast.Call)
        and isinstance(statement.exc.func, ast.Name)
        and statement.exc.func.id == "NotImplementedError"
    )


def test_every_runtime_feature_has_exactly_one_scaffold() -> None:
    """1~43절의 모든 기능 ID가 정확히 하나의 함수로 존재하는지 검증한다."""
    expected = read_runtime_feature_ids()
    actual = set(discover_feature_functions())
    assert actual == expected


def test_mvp_comments_match_dedicated_scope() -> None:
    """MVP 주석이 전용 MVP 범위 문서의 기능 ID와 정확히 일치하는지 검증한다."""
    marked: set[str] = set()
    for feature_id, (_, node, lines) in discover_feature_functions().items():
        previous_line = lines[node.lineno - 2] if node.lineno >= 2 else ""
        if previous_line.startswith("# MVP:"):
            marked.add(feature_id)
    assert marked == read_mvp_feature_ids()


def test_feature_functions_have_korean_docstrings() -> None:
    """모든 기능 함수에 한국어 기능 설명이 포함되었는지 검증한다."""
    for feature_id, (path, node, _) in discover_feature_functions().items():
        docstring = ast.get_docstring(node) or ""
        assert KOREAN_PATTERN.search(docstring), (
            f"한국어 docstring 누락: {feature_id} ({path})"
        )


def test_feature_functions_are_unimplemented_stubs() -> None:
    """요청 범위대로 기능 함수에 실제 구현이 들어가지 않았는지 검증한다."""
    for feature_id, (path, node, _) in discover_feature_functions().items():
        assert is_not_implemented_stub(node), f"스텁이 아닌 함수: {feature_id} ({path})"
