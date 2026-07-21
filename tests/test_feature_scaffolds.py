"""전체 명세 기능과 생성된 함수 스캐폴드의 정합성을 검증한다."""

import ast
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
FEATURE_SPEC = ROOT / "docs" / "agent-api-feature-spec.md"
MVP_SPEC = ROOT / "docs" / "agent-api-mvp-scope.md"
SECTION_PATTERN = re.compile(r"^## (\d+)\.")
TABLE_ID_PATTERN = re.compile(r"^\| ([A-Z][A-Z0-9-]+) \|")
CHECKED_MVP_PATTERN = re.compile(r"^- \[x\] `([A-Z][A-Z0-9-]+)`")
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


def read_checked_mvp_feature_ids() -> set[str]:
    """MVP 체크리스트에서 구현 완료로 표시된 기능 ID를 읽는다."""
    return {
        match.group(1)
        for line in MVP_SPEC.read_text(encoding="utf-8").splitlines()
        if (match := CHECKED_MVP_PATTERN.match(line))
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


def discover_api_facades() -> list[Path]:
    """features 구현 패키지 밖에 있는 공개 api.py facade를 찾는다."""
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
    return [
        path
        for source_root in source_roots
        for path in source_root.rglob("api.py")
        if "features" not in path.relative_to(ROOT).parts
    ]


def discover_facade_exports() -> dict[str, Path]:
    """모든 api.py facade가 다시 노출하는 기능 함수 이름을 찾는다."""
    exported: dict[str, Path] = {}
    for path in discover_api_facades():
        tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        for node in tree.body:
            if not isinstance(node, ast.ImportFrom):
                continue
            for alias in node.names:
                if not FUNCTION_PATTERN.match(alias.name):
                    continue
                feature_id = alias.name.upper().replace("_", "-")
                if feature_id in exported:
                    raise AssertionError(f"중복 facade export: {feature_id}")
                exported[feature_id] = path
    return exported


def discover_facade_all_names() -> set[str]:
    """모든 api.py의 __all__에 등록된 기능 ID 형식 이름을 찾는다.

    명세 1~43절 기능 영역이 아닌 기능 영역(예: 키워드 비서)의 facade는 기능 ID
    형식이 아닌 이름을 노출하므로, 기능 ID 정합성 검증에서는 제외한다.
    """
    names: set[str] = set()
    for path in discover_api_facades():
        tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        for node in tree.body:
            if not isinstance(node, ast.Assign):
                continue
            if not any(
                isinstance(target, ast.Name) and target.id == "__all__"
                for target in node.targets
            ):
                continue
            if not isinstance(node.value, (ast.List, ast.Tuple)):
                raise AssertionError(f"정적 __all__ 목록이 아님: {path}")
            for item in node.value.elts:
                if (
                    isinstance(item, ast.Constant)
                    and isinstance(item.value, str)
                    and FUNCTION_PATTERN.match(item.value)
                ):
                    names.add(item.value)
    return names


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


# 명세 1~43절 기능 영역 facade 43개에, 기능 ID 체계 밖의 기능 영역 facade를 더한 수.
# 키워드 비서(agent/assistant)는 별도 제품 라인이라 기능 ID를 부여하지 않지만,
# "구현은 features/, 공개는 api.py" 구조 규칙은 동일하게 따른다.
EXPECTED_API_FACADES = 44


def test_api_facades_export_every_runtime_feature() -> None:
    """모든 기능 함수가 정확히 하나의 api.py facade에서 공개되는지 검증한다."""
    expected = read_runtime_feature_ids()
    assert len(discover_api_facades()) == EXPECTED_API_FACADES
    assert set(discover_facade_exports()) == expected
    assert discover_facade_all_names() == {
        feature_id.lower().replace("-", "_") for feature_id in expected
    }


def test_api_facades_contain_no_implementation() -> None:
    """api.py가 함수 구현 없이 import facade 역할만 하는지 검증한다."""
    for path in discover_api_facades():
        tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        implemented = [
            node.name
            for node in tree.body
            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))
        ]
        assert implemented == [], f"facade에 함수 구현 존재: {path} ({implemented})"


def test_feature_functions_live_under_features_packages() -> None:
    """모든 기능 함수가 각 기능 영역의 features 패키지 아래에 있는지 검증한다."""
    for feature_id, (path, _, _) in discover_feature_functions().items():
        assert "features" in path.relative_to(ROOT).parts, (
            f"features 패키지 밖의 기능 함수: {feature_id} ({path})"
        )


def test_feature_modules_do_not_import_their_api_facade() -> None:
    """구현 모듈이 공개 api.py를 역참조해 순환 의존성을 만들지 않는지 검증한다."""
    checked_paths = {path for path, _, _ in discover_feature_functions().values()}
    for path in checked_paths:
        relative_parts = path.relative_to(ROOT).parts
        features_index = relative_parts.index("features")
        api_module = ".".join((*relative_parts[:features_index], "api"))
        tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        for node in tree.body:
            relative_api_import = (
                isinstance(node, ast.ImportFrom)
                and node.module == "api"
                and node.level
            )
            absolute_api_import = isinstance(node, ast.ImportFrom) and node.module == api_module
            direct_api_import = isinstance(node, ast.Import) and any(
                alias.name == api_module for alias in node.names
            )
            if relative_api_import or absolute_api_import or direct_api_import:
                raise AssertionError(f"구현 모듈의 facade 역참조: {path}")


def test_external_modules_do_not_import_feature_implementation_modules() -> None:
    """외부 계층이 features 구현 파일을 건너뛰어 직접 참조하지 않는지 검증한다."""
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
            relative_parts = path.relative_to(ROOT).parts
            if "features" in relative_parts or path.name == "api.py":
                continue
            tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
            for node in tree.body:
                if isinstance(node, ast.ImportFrom):
                    module = node.module or ""
                    if module == "features" or ".features" in module:
                        raise AssertionError(f"facade를 우회한 구현 import: {path}")
                if isinstance(node, ast.Import) and any(
                    ".features" in alias.name for alias in node.names
                ):
                    raise AssertionError(f"facade를 우회한 구현 import: {path}")


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


def test_feature_implementation_status_matches_mvp_checklist() -> None:
    """완료 체크 기능만 실행 가능하고 나머지는 명시적 스텁인지 검증한다."""
    implemented = read_checked_mvp_feature_ids() | {"SCH-009"}
    for feature_id, (path, node, _) in discover_feature_functions().items():
        if feature_id in implemented:
            assert not is_not_implemented_stub(node), f"구현이 필요한 함수: {feature_id} ({path})"
        else:
            assert is_not_implemented_stub(node), f"스텁이 아닌 함수: {feature_id} ({path})"
