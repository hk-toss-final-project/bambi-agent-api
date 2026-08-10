#!/bin/sh
# Agent DB에 아직 적용되지 않은 Migration을 실행하거나 최신 상태를 확인한다.

set -eu

SCRIPT_DIR="$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)"
MODE="${1:-}"

# 배포 이미지와 DB 컨테이너에서 사용할 Migration Runner 경로를 결정한다.
resolve_migration_runner() {
    if [ -n "${AGENT_DB_MIGRATION_RUNNER_PATH:-}" ]; then
        printf '%s\n' "$AGENT_DB_MIGRATION_RUNNER_PATH"
    elif [ -f /usr/local/bin/run-agent-db-migrations ]; then
        printf '%s\n' /usr/local/bin/run-agent-db-migrations
    else
        printf '%s\n' "$SCRIPT_DIR/run_agent_db_migrations.sh"
    fi
}

migration_runner="$(resolve_migration_runner)"
if [ ! -f "$migration_runner" ]; then
    echo "Migration Runner를 찾을 수 없습니다: $migration_runner" >&2
    exit 1
fi

/bin/sh "$migration_runner" "$MODE"
