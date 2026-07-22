"""키워드 비서 이력 저장소 — PostgreSQL 우선, 로컬 JSON 폴백.

비서는 개인화를 위해 "이 사용자에게 무엇을 이미 보여줬는지"를 기억해야 한다.
그동안 `data/*.json` 파일에 저장했는데, 파일 방식은 서버를 여러 대로 늘릴 수 없고
재배포 시 유실되며, 파일 전체를 읽고 통째로 덮어써서 동시 요청에 취약하다.

이 모듈은 저장 위치만 갈아끼우는 이음매다. `history.py`·`dedup.py`의 공개 함수
시그니처는 그대로 두고, 실제 읽기·쓰기만 여기로 위임한다(호출부 무수정).

## 백엔드 선택

1. `AGENT_DATABASE_URL`이 설정돼 있고 연결되면 → PostgreSQL
2. 설정이 없으면 → JSON 파일 (로컬 개발)
3. 설정은 있는데 연결이 실패하면 → 경고 로그 + JSON 파일 (기능 정지 대신 성능 저하)

3번을 두는 이유: 비서는 PostgreSQL 없이도 동작하던 제품이고, DB 장애로 화면 전체가
멈추는 것보다 개인화 이력이 로컬에 쌓이는 편이 낫다고 판단했다. 어떤 백엔드를 쓰는지는
기동 시 로그로 남긴다.

동기 API만 제공한다. 비서 파이프라인 자체가 동기이고, 웹 계층이 스레드풀에서 호출한다.
"""

from __future__ import annotations

import json
import logging
import os
import threading
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any, Protocol

from agent.assistant.features import config

logger = logging.getLogger("agent.assistant.storage")


def normalize_keyword(keyword: str) -> str:
    """키워드를 대소문자·공백 차이 없이 조회할 수 있게 정규화한다."""
    return " ".join(keyword.strip().lower().split())


class HistoryStore(Protocol):
    """비서 이력 저장소가 제공해야 하는 연산."""

    def get_watched_video_ids(self, user_id: str, keyword: str) -> set[str]: ...

    def record_watch(
        self, user_id: str, keyword: str, video_id: str, title: str, url: str
    ) -> None: ...

    def get_reported_article_keys(self, user_id: str, keyword: str) -> set[str]: ...

    def record_reported_article(
        self, user_id: str, keyword: str, url_key: str, title: str, url: str
    ) -> None: ...

    def get_collected_entries(
        self, user_id: str, keyword: str
    ) -> dict[str, dict[str, object]]: ...

    def record_collected(
        self,
        user_id: str,
        keyword: str,
        url_key: str,
        title: str,
        url: str,
        *,
        first_seen: datetime,
        score: float | None,
    ) -> datetime: ...

    def load_recent_report_items(
        self, user_id: str, keyword: str, *, cutoff: datetime, exclude_date: object
    ) -> list[dict[str, object]]: ...

    def record_report_items(
        self,
        user_id: str,
        keyword: str,
        items: list[dict[str, object]],
        *,
        reference: datetime,
        cutoff: datetime,
    ) -> None: ...


# ── JSON 파일 백엔드 ──────────────────────────────────────────────────────


class JsonHistoryStore:
    """로컬 JSON 파일 저장소 (기본값, 단일 프로세스 개발용)."""

    def __init__(self, data_dir: Path | None = None) -> None:
        """저장 디렉터리를 정한다. 생략하면 config.DATA_DIR을 쓴다."""
        self._data_dir = data_dir or config.DATA_DIR
        self._lock = threading.Lock()

    def _path(self, name: str) -> Path:
        """이력 종류별 파일 경로를 만든다."""
        return self._data_dir / name

    def _load(self, name: str) -> dict[str, Any]:
        """이력 파일을 읽는다. 없거나 깨졌으면 빈 구조를 반환한다."""
        path = self._path(name)
        if not path.exists():
            return {}
        try:
            return json.loads(path.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError):
            return {}

    def _save(self, name: str, data: dict[str, Any]) -> None:
        """이력 파일을 저장한다."""
        self._data_dir.mkdir(parents=True, exist_ok=True)
        self._path(name).write_text(
            json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8"
        )

    def _keys(self, name: str, user_id: str, keyword: str) -> set[str]:
        """사용자·키워드 하위 항목의 키 집합을 반환한다."""
        data = self._load(name)
        return set(data.get(user_id, {}).get(normalize_keyword(keyword), {}))

    def _put(
        self, name: str, user_id: str, keyword: str, key: str, value: dict[str, object]
    ) -> None:
        """사용자·키워드 하위에 항목 하나를 기록한다."""
        with self._lock:
            data = self._load(name)
            entry = data.setdefault(user_id, {}).setdefault(normalize_keyword(keyword), {})
            entry[key] = value
            self._save(name, data)

    def get_watched_video_ids(self, user_id: str, keyword: str) -> set[str]:
        """사용자가 해당 키워드에서 이미 본 영상 ID 집합을 반환한다."""
        return self._keys("watch_history.json", user_id, keyword)

    def record_watch(
        self, user_id: str, keyword: str, video_id: str, title: str, url: str
    ) -> None:
        """클릭한 영상을 시청 이력에 기록한다."""
        self._put(
            "watch_history.json",
            user_id,
            keyword,
            video_id,
            {"title": title, "url": url, "watched_at": datetime.now(UTC).isoformat()},
        )

    def get_reported_article_keys(self, user_id: str, keyword: str) -> set[str]:
        """이미 보고한 기사의 정규 URL 집합을 반환한다."""
        return self._keys("article_history.json", user_id, keyword)

    def record_reported_article(
        self, user_id: str, keyword: str, url_key: str, title: str, url: str
    ) -> None:
        """리포트에 실린 기사를 보고 이력에 기록한다."""
        self._put(
            "article_history.json",
            user_id,
            keyword,
            url_key,
            {"title": title, "url": url, "reported_at": datetime.now(UTC).isoformat()},
        )

    def get_collected_entries(
        self, user_id: str, keyword: str
    ) -> dict[str, dict[str, object]]:
        """사용자·키워드의 수집 이력을 반환한다."""
        data = self._load("collect_history.json")
        return dict(data.get(user_id, {}).get(normalize_keyword(keyword), {}))

    def record_collected(
        self,
        user_id: str,
        keyword: str,
        url_key: str,
        title: str,
        url: str,
        *,
        first_seen: datetime,
        score: float | None,
    ) -> datetime:
        """수집 문서를 기록하고 확정된 first_seen을 반환한다(기존 값 유지)."""
        with self._lock:
            data = self._load("collect_history.json")
            entry = data.setdefault(user_id, {}).setdefault(normalize_keyword(keyword), {})
            existing = entry.get(url_key)
            resolved = first_seen
            if existing and existing.get("first_seen"):
                try:
                    resolved = datetime.fromisoformat(str(existing["first_seen"]))
                except ValueError:
                    resolved = first_seen
            record: dict[str, object] = {
                "title": title,
                "url": url,
                "first_seen": resolved.isoformat(),
            }
            if score is not None:
                record["score"] = score
            elif existing and existing.get("score") is not None:
                record["score"] = existing["score"]
            entry[url_key] = record
            self._save("collect_history.json", data)
        return resolved

    def load_recent_report_items(
        self, user_id: str, keyword: str, *, cutoff: datetime, exclude_date: object
    ) -> list[dict[str, object]]:
        """중복 검사에 쓸 최근 보고 아이템을 반환한다."""
        data = self._load("report_embedding_history.json")
        entries = data.get(user_id, {}).get(normalize_keyword(keyword), {})
        items: list[dict[str, object]] = []
        for url_key, entry in entries.items():
            reported_at = _parse_iso(str(entry.get("reported_at") or ""))
            if reported_at is None or reported_at < cutoff:
                continue
            if exclude_date is not None and reported_at.date() == exclude_date:
                continue
            items.append({**entry, "url_key": url_key, "reported_at_dt": reported_at})
        return items

    def record_report_items(
        self,
        user_id: str,
        keyword: str,
        items: list[dict[str, object]],
        *,
        reference: datetime,
        cutoff: datetime,
    ) -> None:
        """보고 아이템 임베딩을 기록하고 오래된 항목을 정리한다."""
        with self._lock:
            data = self._load("report_embedding_history.json")
            entry = data.setdefault(user_id, {}).setdefault(normalize_keyword(keyword), {})
            for url_key in list(entry):
                reported_at = _parse_iso(str(entry[url_key].get("reported_at") or ""))
                if reported_at is None or reported_at < cutoff:
                    del entry[url_key]
            for item in items:
                url_key = str(item.get("url_key") or "")
                embedding = item.get("embedding")
                if not url_key or not isinstance(embedding, list):
                    continue
                entry[url_key] = {
                    "title": str(item.get("title") or ""),
                    "embedding": embedding,
                    "reported_at": reference.isoformat(),
                }
            self._save("report_embedding_history.json", data)


def _parse_iso(raw: str) -> datetime | None:
    """ISO 문자열을 timezone-aware datetime으로 파싱한다. 실패 시 None."""
    if not raw:
        return None
    try:
        parsed = datetime.fromisoformat(raw)
    except ValueError:
        return None
    return parsed if parsed.tzinfo else parsed.replace(tzinfo=UTC)


# ── PostgreSQL 백엔드 ─────────────────────────────────────────────────────


class PostgresHistoryStore:
    """PostgreSQL 저장소 (운영 기본값).

    psycopg 동기 API를 쓴다 — 비서 파이프라인이 동기이고, 웹 계층이 스레드풀에서
    호출하기 때문이다. 연결은 호출마다 열고 닫는다. 비서 실행 한 번에 이력 접근이
    수십 회 수준이라 Pool 없이 충분하고, 이벤트 루프 종류에 따라 Pool이 깨지는
    문제(Windows ProactorEventLoop)도 피할 수 있다.
    """

    def __init__(self, dsn: str) -> None:
        """연결 문자열을 보관한다."""
        self._dsn = dsn

    def _connect(self):
        """psycopg 동기 연결을 연다."""
        import psycopg

        return psycopg.connect(self._dsn)

    def _fetch_keys(self, sql: str, params: tuple) -> set[str]:
        """단일 컬럼 조회 결과를 집합으로 반환한다."""
        with self._connect() as connection, connection.cursor() as cursor:
            cursor.execute(sql, params)
            return {row[0] for row in cursor.fetchall()}

    def get_watched_video_ids(self, user_id: str, keyword: str) -> set[str]:
        """사용자가 해당 키워드에서 이미 본 영상 ID 집합을 반환한다."""
        return self._fetch_keys(
            "SELECT video_id FROM agent.assistant_watched_videos "
            "WHERE user_id = %s AND keyword_normalized = %s",
            (user_id, normalize_keyword(keyword)),
        )

    def record_watch(
        self, user_id: str, keyword: str, video_id: str, title: str, url: str
    ) -> None:
        """클릭한 영상을 시청 이력에 기록한다(같은 영상은 시각만 갱신)."""
        with self._connect() as connection, connection.cursor() as cursor:
            cursor.execute(
                "INSERT INTO agent.assistant_watched_videos "
                "(user_id, keyword_normalized, video_id, title, url) "
                "VALUES (%s, %s, %s, %s, %s) "
                "ON CONFLICT (user_id, keyword_normalized, video_id) DO UPDATE "
                "SET title = EXCLUDED.title, url = EXCLUDED.url, "
                "    watched_at = clock_timestamp()",
                (user_id, normalize_keyword(keyword), video_id, title, url),
            )

    def get_reported_article_keys(self, user_id: str, keyword: str) -> set[str]:
        """이미 보고한 기사의 정규 URL 집합을 반환한다."""
        return self._fetch_keys(
            "SELECT url_key FROM agent.assistant_reported_articles "
            "WHERE user_id = %s AND keyword_normalized = %s",
            (user_id, normalize_keyword(keyword)),
        )

    def record_reported_article(
        self, user_id: str, keyword: str, url_key: str, title: str, url: str
    ) -> None:
        """리포트에 실린 기사를 보고 이력에 기록한다."""
        with self._connect() as connection, connection.cursor() as cursor:
            cursor.execute(
                "INSERT INTO agent.assistant_reported_articles "
                "(user_id, keyword_normalized, url_key, title, url) "
                "VALUES (%s, %s, %s, %s, %s) "
                "ON CONFLICT (user_id, keyword_normalized, url_key) DO UPDATE "
                "SET title = EXCLUDED.title, url = EXCLUDED.url, "
                "    reported_at = clock_timestamp()",
                (user_id, normalize_keyword(keyword), url_key, title, url),
            )

    def get_collected_entries(
        self, user_id: str, keyword: str
    ) -> dict[str, dict[str, object]]:
        """사용자·키워드의 수집 이력을 파일 백엔드와 같은 모양으로 반환한다."""
        with self._connect() as connection, connection.cursor() as cursor:
            cursor.execute(
                "SELECT url_key, title, url, first_seen, score "
                "FROM agent.assistant_collected_documents "
                "WHERE user_id = %s AND keyword_normalized = %s",
                (user_id, normalize_keyword(keyword)),
            )
            entries: dict[str, dict[str, object]] = {}
            for url_key, title, url, first_seen, score in cursor.fetchall():
                entry: dict[str, object] = {
                    "title": title,
                    "url": url,
                    "first_seen": first_seen.isoformat(),
                }
                if score is not None:
                    entry["score"] = score
                entries[url_key] = entry
            return entries

    def record_collected(
        self,
        user_id: str,
        keyword: str,
        url_key: str,
        title: str,
        url: str,
        *,
        first_seen: datetime,
        score: float | None,
    ) -> datetime:
        """수집 문서를 기록하고 확정된 first_seen을 반환한다.

        first_seen은 덮어쓰지 않는다(재수집을 새 문서로 오인하지 않기 위해).
        score는 최신 값으로 갱신하되, 이번에 값이 없으면 기존 값을 남긴다.
        """
        with self._connect() as connection, connection.cursor() as cursor:
            cursor.execute(
                "INSERT INTO agent.assistant_collected_documents "
                "(user_id, keyword_normalized, url_key, title, url, first_seen, score) "
                "VALUES (%s, %s, %s, %s, %s, %s, %s) "
                "ON CONFLICT (user_id, keyword_normalized, url_key) DO UPDATE "
                "SET title = EXCLUDED.title, url = EXCLUDED.url, "
                "    score = COALESCE(EXCLUDED.score, "
                "                     agent.assistant_collected_documents.score), "
                "    updated_at = clock_timestamp() "
                "RETURNING first_seen",
                (
                    user_id,
                    normalize_keyword(keyword),
                    url_key,
                    title,
                    url,
                    first_seen,
                    score,
                ),
            )
            row = cursor.fetchone()
            return row[0] if row else first_seen

    def load_recent_report_items(
        self, user_id: str, keyword: str, *, cutoff: datetime, exclude_date: object
    ) -> list[dict[str, object]]:
        """중복 검사에 쓸 최근 보고 아이템을 반환한다.

        파일 백엔드가 1.6MB 전체를 읽던 것과 달리, cutoff 이후 행만 DB가 골라 준다.
        """
        sql = (
            "SELECT url_key, title, embedding, reported_at "
            "FROM agent.assistant_report_embeddings "
            "WHERE user_id = %s AND keyword_normalized = %s AND reported_at >= %s"
        )
        params: list[object] = [user_id, normalize_keyword(keyword), cutoff]
        if exclude_date is not None:
            sql += " AND reported_at::date <> %s"
            params.append(exclude_date)

        with self._connect() as connection, connection.cursor() as cursor:
            cursor.execute(sql, tuple(params))
            return [
                {
                    "url_key": url_key,
                    "title": title,
                    "embedding": _to_float_list(embedding),
                    "reported_at": reported_at.isoformat(),
                    "reported_at_dt": reported_at,
                }
                for url_key, title, embedding, reported_at in cursor.fetchall()
            ]

    def record_report_items(
        self,
        user_id: str,
        keyword: str,
        items: list[dict[str, object]],
        *,
        reference: datetime,
        cutoff: datetime,
    ) -> None:
        """보고 아이템 임베딩을 기록하고 오래된 항목을 정리한다."""
        normalized = normalize_keyword(keyword)
        with self._connect() as connection, connection.cursor() as cursor:
            cursor.execute(
                "DELETE FROM agent.assistant_report_embeddings "
                "WHERE user_id = %s AND keyword_normalized = %s AND reported_at < %s",
                (user_id, normalized, cutoff),
            )
            for item in items:
                url_key = str(item.get("url_key") or "")
                embedding = item.get("embedding")
                if not url_key or not isinstance(embedding, list):
                    continue
                cursor.execute(
                    "INSERT INTO agent.assistant_report_embeddings "
                    "(user_id, keyword_normalized, url_key, title, embedding, reported_at) "
                    "VALUES (%s, %s, %s, %s, %s, %s) "
                    "ON CONFLICT (user_id, keyword_normalized, url_key) DO UPDATE "
                    "SET title = EXCLUDED.title, embedding = EXCLUDED.embedding, "
                    "    reported_at = EXCLUDED.reported_at",
                    (
                        user_id,
                        normalized,
                        url_key,
                        str(item.get("title") or ""),
                        _to_vector_literal(embedding),
                        reference,
                    ),
                )


def _to_vector_literal(embedding: list[float]) -> str:
    """파이썬 리스트를 pgvector 입력 리터럴로 바꾼다."""
    return "[" + ",".join(str(float(value)) for value in embedding) + "]"


def _to_float_list(raw: object) -> list[float]:
    """pgvector 조회 결과를 파이썬 float 리스트로 바꾼다.

    psycopg는 vector 타입 등록 여부에 따라 문자열 또는 시퀀스를 돌려준다.
    """
    if isinstance(raw, (list, tuple)):
        return [float(value) for value in raw]
    text = str(raw).strip().strip("[]")
    if not text:
        return []
    return [float(part) for part in text.split(",")]


# ── 백엔드 선택 ───────────────────────────────────────────────────────────

_store: HistoryStore | None = None
_store_lock = threading.Lock()


def _database_url() -> str | None:
    """비서 이력에 쓸 연결 문자열을 찾는다. 없으면 None."""
    return (
        os.environ.get("ASSISTANT_DATABASE_URL")
        or os.environ.get("AGENT_DATABASE_URL")
        or None
    )


def _build_store() -> HistoryStore:
    """설정과 연결 가능 여부를 보고 사용할 저장소를 고른다."""
    dsn = _database_url()
    if not dsn:
        logger.info("비서 이력 저장소: 로컬 JSON 파일 (DB 연결 문자열 미설정)")
        return JsonHistoryStore()

    store = PostgresHistoryStore(dsn)
    try:
        with store._connect() as connection, connection.cursor() as cursor:
            cursor.execute("SELECT to_regclass('agent.assistant_collected_documents')")
            row = cursor.fetchone()
            if not row or row[0] is None:
                raise RuntimeError(
                    "비서 이력 테이블이 없습니다. "
                    "database/migrations/0007_assistant_history.sql을 적용하세요."
                )
    except Exception as error:
        logger.warning(
            "비서 이력 저장소: PostgreSQL을 쓸 수 없어 로컬 JSON 파일로 폴백합니다 "
            "(개인화 이력이 이 프로세스에만 쌓입니다): %s: %s",
            type(error).__name__,
            error,
        )
        return JsonHistoryStore()

    logger.info("비서 이력 저장소: PostgreSQL")
    return store


def get_store() -> HistoryStore:
    """사용할 이력 저장소를 반환한다(최초 1회 선택 후 재사용)."""
    global _store
    if _store is None:
        with _store_lock:
            if _store is None:
                _store = _build_store()
    return _store


def set_store(store: HistoryStore | None) -> None:
    """저장소를 교체한다(테스트·이관 스크립트용). None이면 다음 호출에 다시 고른다."""
    global _store
    with _store_lock:
        _store = store


def lookback_cutoff(reference: datetime, lookback_days: int | None = None) -> datetime:
    """중복 검사 조회 하한 시각을 계산한다."""
    days = config.DEDUP_LOOKBACK_DAYS if lookback_days is None else lookback_days
    return reference - timedelta(days=days)
