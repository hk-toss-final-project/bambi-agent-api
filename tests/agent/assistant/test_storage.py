"""비서 이력 저장소(storage) 검증.

JSON 백엔드는 실제 파일로, PostgreSQL 백엔드는 SQL 조립만 가짜 커서로 검증한다
(실제 DB 없이도 `uv run pytest`가 통과해야 하므로).
"""

from datetime import UTC, datetime, timedelta

import pytest

from agent.assistant.features import storage

_NOW = datetime(2026, 7, 20, 9, 0, tzinfo=UTC)


# ── JSON 백엔드 ───────────────────────────────────────────────────────────


def test_json_store_roundtrip(tmp_path) -> None:
    """기록한 값이 그대로 조회된다."""
    store = storage.JsonHistoryStore(tmp_path)

    store.record_watch("minji", "코스피", "v1", "제목", "https://y.test/1")
    store.record_reported_article("minji", "코스피", "https://a.test/1", "기사", "https://a.test/1")

    assert store.get_watched_video_ids("minji", "코스피") == {"v1"}
    assert store.get_reported_article_keys("minji", "코스피") == {"https://a.test/1"}


def test_json_store_keeps_first_seen_on_recollect(tmp_path) -> None:
    """같은 URL을 다시 수집해도 first_seen은 덮어쓰지 않는다."""
    store = storage.JsonHistoryStore(tmp_path)
    original = _NOW - timedelta(days=3)

    store.record_collected("minji", "코스피", "u1", "제목", "url", first_seen=original, score=0.1)
    resolved = store.record_collected(
        "minji", "코스피", "u1", "제목", "url", first_seen=_NOW, score=0.9
    )

    assert resolved == original
    entry = store.get_collected_entries("minji", "코스피")["u1"]
    assert entry["score"] == 0.9      # 점수는 최신값으로 갱신
    assert entry["first_seen"] == original.isoformat()


def test_json_store_isolates_users_and_keywords(tmp_path) -> None:
    """다른 사용자·키워드의 이력은 섞이지 않는다."""
    store = storage.JsonHistoryStore(tmp_path)
    store.record_watch("minji", "코스피", "v1", "", "")
    store.record_watch("yuri", "코스피", "v2", "", "")
    store.record_watch("minji", "환율", "v3", "", "")

    assert store.get_watched_video_ids("minji", "코스피") == {"v1"}
    assert store.get_watched_video_ids("yuri", "코스피") == {"v2"}
    assert store.get_watched_video_ids("minji", "환율") == {"v3"}


def test_data_dir_points_to_repository_root(monkeypatch) -> None:
    """폴백 데이터 디렉터리는 저장소 루트의 data/를 가리킨다 (회귀 방지).

    파일이 features/ 아래로 옮겨졌을 때 상대 경로 계산이 한 단계 밀려 agent/data/를
    가리켰고, 그 결과 이력이 data/와 agent/data/ 두 곳으로 쪼개졌다.
    """
    import importlib

    from agent.assistant.features import config

    monkeypatch.delenv("ASSISTANT_DATA_DIR", raising=False)
    importlib.reload(config)
    try:
        # 저장소 루트에는 pyproject.toml이 있다.
        assert (config.DATA_DIR.parent / "pyproject.toml").exists()
        assert config.DATA_DIR.name == "data"
        assert config.DATA_DIR.parent.name != "agent"
    finally:
        importlib.reload(config)


def test_normalize_keyword_ignores_case_and_spacing() -> None:
    """키워드는 대소문자·공백 차이 없이 같은 키로 취급한다."""
    assert storage.normalize_keyword("  Kospi   지수 ") == "kospi 지수"


# ── 백엔드 선택 ───────────────────────────────────────────────────────────


def test_uses_json_when_no_database_url(monkeypatch) -> None:
    """연결 문자열이 없으면 JSON 저장소를 쓴다 (로컬 개발)."""
    monkeypatch.delenv("ASSISTANT_DATABASE_URL", raising=False)
    monkeypatch.delenv("AGENT_DATABASE_URL", raising=False)
    storage.set_store(None)

    assert isinstance(storage._build_store(), storage.JsonHistoryStore)


def test_falls_back_to_json_when_database_unreachable(monkeypatch) -> None:
    """DB가 설정돼 있어도 연결이 안 되면 JSON으로 폴백한다.

    비서는 PostgreSQL 없이도 동작하던 제품이라, DB 장애로 화면 전체가 멈추는 것보다
    이력이 로컬에 쌓이는 편이 낫다고 판단했다.
    """
    monkeypatch.setenv("AGENT_DATABASE_URL", "postgresql://nope/nope")

    def boom(self):
        raise ConnectionError("연결 불가")

    monkeypatch.setattr(storage.PostgresHistoryStore, "_connect", boom)
    storage.set_store(None)

    assert isinstance(storage._build_store(), storage.JsonHistoryStore)


def test_set_store_overrides_selection(tmp_path) -> None:
    """set_store로 저장소를 교체할 수 있다 (테스트·이관 스크립트용)."""
    injected = storage.JsonHistoryStore(tmp_path)
    storage.set_store(injected)
    try:
        assert storage.get_store() is injected
    finally:
        storage.set_store(None)


# ── pgvector 변환 ─────────────────────────────────────────────────────────


def test_vector_literal_roundtrip() -> None:
    """임베딩을 pgvector 리터럴로 바꾸고 다시 읽어올 수 있다."""
    literal = storage._to_vector_literal([0.1, -0.25, 0.0])

    assert literal == "[0.1,-0.25,0.0]"
    assert storage._to_float_list(literal) == pytest.approx([0.1, -0.25, 0.0])


def test_float_list_accepts_sequence_and_empty() -> None:
    """psycopg가 시퀀스로 돌려주는 경우와 빈 값도 처리한다."""
    assert storage._to_float_list([0.5, 1]) == [0.5, 1.0]
    assert storage._to_float_list("[]") == []
    assert storage._to_float_list("") == []


# ── PostgreSQL 백엔드 (가짜 커서) ─────────────────────────────────────────


class _FakeCursor:
    """실행된 SQL과 파라미터를 기록하는 가짜 커서."""

    def __init__(self, rows: list[tuple]) -> None:
        self.rows = rows
        self.executed: list[tuple[str, tuple]] = []

    def execute(self, sql, params=()):
        """SQL 실행을 기록한다."""
        self.executed.append((" ".join(sql.split()), params))

    def fetchall(self):
        """준비된 행을 돌려준다."""
        return self.rows

    def fetchone(self):
        """준비된 첫 행을 돌려준다."""
        return self.rows[0] if self.rows else None

    def __enter__(self):
        return self

    def __exit__(self, *args):
        return False


class _FakeConnection:
    """가짜 커서를 내주는 연결."""

    def __init__(self, cursor: _FakeCursor) -> None:
        self._cursor = cursor

    def cursor(self):
        """가짜 커서를 반환한다."""
        return self._cursor

    def __enter__(self):
        return self

    def __exit__(self, *args):
        return False


def _postgres_store(monkeypatch, rows: list[tuple]) -> tuple:
    """가짜 연결을 쓰는 PostgreSQL 저장소와 커서를 만든다."""
    cursor = _FakeCursor(rows)
    store = storage.PostgresHistoryStore("postgresql://test")
    monkeypatch.setattr(store, "_connect", lambda: _FakeConnection(cursor))
    return store, cursor


def test_postgres_scopes_query_by_user_and_keyword(monkeypatch) -> None:
    """조회는 사용자·정규화 키워드로 범위를 좁힌다."""
    store, cursor = _postgres_store(monkeypatch, [("v1",), ("v2",)])

    assert store.get_watched_video_ids("minji", "  코스피 ") == {"v1", "v2"}
    sql, params = cursor.executed[0]
    assert "assistant_watched_videos" in sql
    assert params == ("minji", "코스피")


def test_postgres_recent_items_filter_by_cutoff_and_date(monkeypatch) -> None:
    """최근 조회는 cutoff 이후 행만 가져오고, 오늘 기록은 제외할 수 있다."""
    store, cursor = _postgres_store(
        monkeypatch, [("u1", "제목", "[0.1,0.2]", _NOW - timedelta(days=1))]
    )

    items = store.load_recent_report_items(
        "minji", "코스피", cutoff=_NOW - timedelta(days=7), exclude_date=_NOW.date()
    )

    sql, params = cursor.executed[0]
    assert "reported_at >= %s" in sql
    assert "reported_at::date <> %s" in sql   # 오늘 기록 제외
    assert params[-1] == _NOW.date()
    assert items[0]["embedding"] == pytest.approx([0.1, 0.2])


def test_postgres_record_report_items_prunes_then_inserts(monkeypatch) -> None:
    """기록 시 오래된 항목을 먼저 지우고 새 항목을 넣는다."""
    store, cursor = _postgres_store(monkeypatch, [])

    store.record_report_items(
        "minji",
        "코스피",
        [{"url_key": "u1", "title": "제목", "embedding": [0.1, 0.2]}],
        reference=_NOW,
        cutoff=_NOW - timedelta(days=7),
    )

    statements = [sql for sql, _ in cursor.executed]
    assert statements[0].startswith("DELETE FROM agent.assistant_report_embeddings")
    assert "INSERT INTO agent.assistant_report_embeddings" in statements[1]
    assert "ON CONFLICT" in statements[1]      # 같은 url_key는 덮어쓴다


def test_postgres_record_report_items_skips_invalid(monkeypatch) -> None:
    """url_key나 임베딩이 없는 항목은 넣지 않는다."""
    store, cursor = _postgres_store(monkeypatch, [])

    store.record_report_items(
        "minji",
        "코스피",
        [{"url_key": "", "embedding": [0.1]}, {"url_key": "u1", "embedding": "벡터아님"}],
        reference=_NOW,
        cutoff=_NOW - timedelta(days=7),
    )

    inserts = [sql for sql, _ in cursor.executed if sql.startswith("INSERT")]
    assert inserts == []


def test_postgres_collected_keeps_first_seen_via_returning(monkeypatch) -> None:
    """수집 기록은 RETURNING으로 확정된 first_seen을 돌려받는다."""
    stored_first_seen = _NOW - timedelta(days=3)
    store, cursor = _postgres_store(monkeypatch, [(stored_first_seen,)])

    resolved = store.record_collected(
        "minji", "코스피", "u1", "제목", "url", first_seen=_NOW, score=0.5
    )

    sql, _ = cursor.executed[0]
    assert "RETURNING first_seen" in sql
    # first_seen은 갱신 대상에서 빠져 있어야 한다(재수집을 새 문서로 오인하지 않기 위해).
    assert "SET title = EXCLUDED.title" in sql
    assert "first_seen = EXCLUDED.first_seen" not in sql
    assert resolved == stored_first_seen
