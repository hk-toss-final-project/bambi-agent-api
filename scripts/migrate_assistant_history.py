"""로컬 JSON에 쌓인 키워드 비서 이력을 PostgreSQL로 이관한다 (일회성).

`data/*.json`에 있던 시청·보고·수집 이력과 보고서 임베딩을 0007 마이그레이션으로
만든 테이블에 옮긴다. 같은 키가 이미 있으면 덮어쓰므로 여러 번 실행해도 안전하다
(멱등). 원본 JSON은 지우지 않는다 — 이관 결과를 확인한 뒤 사용자가 직접 정리한다.

실행:
    uv run python scripts/migrate_assistant_history.py --dry-run   # 건수만 확인
    uv run python scripts/migrate_assistant_history.py             # 실제 이관

선행 조건:
- `AGENT_DATABASE_URL`(또는 `ASSISTANT_DATABASE_URL`)이 설정돼 있어야 한다.
- `database/migrations/0007_assistant_history.sql`이 적용돼 있어야 한다.
"""

from __future__ import annotations

import argparse
import json
import sys
from datetime import UTC, datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")

from dotenv import load_dotenv

from agent.assistant.features import config, storage


def _load_json(path: Path) -> dict:
    """이력 파일을 읽는다. 없거나 깨졌으면 빈 구조를 반환한다."""
    if not path.exists():
        return {}
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError) as error:
        print(f"  ! {path.name} 읽기 실패: {error}")
        return {}


def _parse_iso(raw: object) -> datetime | None:
    """ISO 문자열을 timezone-aware datetime으로 파싱한다."""
    text = str(raw or "")
    if not text:
        return None
    try:
        parsed = datetime.fromisoformat(text)
    except ValueError:
        return None
    return parsed if parsed.tzinfo else parsed.replace(tzinfo=UTC)


def _iterate(data: dict):
    """{user: {keyword: {key: entry}}} 구조를 (user, keyword, key, entry)로 펼친다."""
    for user_id, keywords in data.items():
        if not isinstance(keywords, dict):
            continue
        for keyword, entries in keywords.items():
            if not isinstance(entries, dict):
                continue
            for key, entry in entries.items():
                if isinstance(entry, dict):
                    yield user_id, keyword, key, entry


def migrate(store: storage.HistoryStore, data_dir: Path, *, dry_run: bool) -> dict[str, int]:
    """JSON 이력을 저장소로 옮기고 종류별 건수를 반환한다."""
    counts = {"watch": 0, "article": 0, "collect": 0, "embedding": 0}

    for user_id, keyword, video_id, entry in _iterate(_load_json(data_dir / "watch_history.json")):
        counts["watch"] += 1
        if not dry_run:
            store.record_watch(
                user_id, keyword, video_id,
                str(entry.get("title") or ""), str(entry.get("url") or ""),
            )

    for user_id, keyword, url_key, entry in _iterate(
        _load_json(data_dir / "article_history.json")
    ):
        counts["article"] += 1
        if not dry_run:
            store.record_reported_article(
                user_id, keyword, url_key,
                str(entry.get("title") or ""), str(entry.get("url") or ""),
            )

    for user_id, keyword, url_key, entry in _iterate(
        _load_json(data_dir / "collect_history.json")
    ):
        counts["collect"] += 1
        if dry_run:
            continue
        score = entry.get("score")
        store.record_collected(
            user_id, keyword, url_key,
            str(entry.get("title") or ""), str(entry.get("url") or ""),
            first_seen=_parse_iso(entry.get("first_seen")) or datetime.now(UTC),
            score=float(score) if score is not None else None,
        )

    # 임베딩은 사용자·키워드 단위로 묶어 한 번에 기록한다(청소 로직을 그대로 태우기 위해).
    grouped: dict[tuple[str, str], list[dict[str, object]]] = {}
    latest: dict[tuple[str, str], datetime] = {}
    for user_id, keyword, url_key, entry in _iterate(
        _load_json(data_dir / "report_embedding_history.json")
    ):
        embedding = entry.get("embedding")
        if not isinstance(embedding, list):
            continue
        reported_at = _parse_iso(entry.get("reported_at")) or datetime.now(UTC)
        scope = (user_id, keyword)
        grouped.setdefault(scope, []).append(
            {"url_key": url_key, "title": str(entry.get("title") or ""), "embedding": embedding}
        )
        latest[scope] = max(latest.get(scope, reported_at), reported_at)
        counts["embedding"] += 1

    if not dry_run:
        for scope, items in grouped.items():
            user_id, keyword = scope
            reference = latest[scope]
            # cutoff를 아주 과거로 두어 이관 중에는 아무것도 청소하지 않는다.
            store.record_report_items(
                user_id, keyword, items,
                reference=reference,
                cutoff=datetime(1970, 1, 1, tzinfo=UTC),
            )

    return counts


def main() -> int:
    """이관을 실행하고 결과를 출력한다."""
    parser = argparse.ArgumentParser(description="비서 이력 JSON → PostgreSQL 이관")
    parser.add_argument("--dry-run", action="store_true", help="쓰지 않고 건수만 센다")
    parser.add_argument("--data-dir", default=None, help="이력 JSON 디렉터리 (기본: config.DATA_DIR)")
    args = parser.parse_args()

    load_dotenv()
    data_dir = Path(args.data_dir) if args.data_dir else config.DATA_DIR
    print(f"원본 디렉터리: {data_dir}")

    if args.dry_run:
        store: storage.HistoryStore = storage.JsonHistoryStore(data_dir)
        print("모드: dry-run (쓰지 않음)\n")
    else:
        dsn = storage._database_url()
        if not dsn:
            print("오류: AGENT_DATABASE_URL(또는 ASSISTANT_DATABASE_URL)이 필요합니다.")
            return 1
        store = storage.PostgresHistoryStore(dsn)
        try:
            with store._connect() as connection, connection.cursor() as cursor:
                cursor.execute("SELECT to_regclass('agent.assistant_collected_documents')")
                row = cursor.fetchone()
                if not row or row[0] is None:
                    print("오류: 0007_assistant_history.sql 마이그레이션을 먼저 적용하세요.")
                    return 1
        except Exception as error:
            print(f"오류: PostgreSQL 연결 실패 — {type(error).__name__}: {error}")
            return 1
        print("모드: 실제 이관 (PostgreSQL)\n")

    counts = migrate(store, data_dir, dry_run=args.dry_run)

    labels = {
        "watch": "시청 이력",
        "article": "보고 기사",
        "collect": "수집 문서",
        "embedding": "보고서 임베딩",
    }
    for key, label in labels.items():
        print(f"  {label:14s} {counts[key]:6d}건")
    print(f"\n  합계 {sum(counts.values())}건")

    if args.dry_run:
        print("\ndry-run이므로 아무것도 쓰지 않았습니다.")
    else:
        print("\n이관 완료. 원본 JSON은 그대로 두었으니 확인 후 직접 정리하세요.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
