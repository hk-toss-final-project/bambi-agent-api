#!/bin/sh
# Agent DB에 아직 적용되지 않은 SQL Migration을 순서대로 안전하게 실행한다.

set -eu

MIGRATION_DIR="${AGENT_DB_MIGRATION_DIR:-/opt/bambi/migrations}"
WAIT_SECONDS="${AGENT_DB_MIGRATION_WAIT_SECONDS:-60}"
LOCK_KEY="764224901"
MODE="${1:-}"
DATABASE_URL="${AGENT_DATABASE_URL:-}"

PGHOST="${PGHOST:-127.0.0.1}"
PGPORT="${PGPORT:-5432}"
PGDATABASE="${PGDATABASE:-${POSTGRES_DB:-postgres}}"
PGUSER="${PGUSER:-${POSTGRES_USER:-postgres}}"
PGPASSWORD="${PGPASSWORD:-${POSTGRES_PASSWORD:-}}"
export PGHOST PGPORT PGDATABASE PGUSER PGPASSWORD

# 배포 환경의 URL 또는 로컬 libpq 환경변수로 psql을 실행한다.
run_psql() {
    if [ -n "$DATABASE_URL" ]; then
        psql -d "$DATABASE_URL" "$@"
        return
    fi

    psql "$@"
}

# 선택된 연결 방식으로 PostgreSQL 준비 상태를 확인한다.
database_is_ready() {
    if [ -n "$DATABASE_URL" ]; then
        pg_isready -q -d "$DATABASE_URL"
        return
    fi

    pg_isready -q -h "$PGHOST" -p "$PGPORT" -U "$PGUSER" -d "$PGDATABASE"
}

set -- "$MIGRATION_DIR"/[0-9][0-9][0-9][0-9]_*.sql
if [ ! -f "$1" ]; then
    echo "Migration 파일을 찾을 수 없습니다: $MIGRATION_DIR" >&2
    exit 1
fi

latest_path=""
for migration_path in "$MIGRATION_DIR"/[0-9][0-9][0-9][0-9]_*.sql; do
    latest_path="$migration_path"
done
latest_name="$(basename "$latest_path")"
latest_prefix="${latest_name%%_*}"
latest_version="$(printf '%s' "$latest_prefix" | sed 's/^0*//')"
latest_version="${latest_version:-0}"

if [ "$MODE" = "--check" ]; then
    run_psql -X -q -t -A -v ON_ERROR_STOP=1 -c \
        "SELECT COALESCE((SELECT max(version) FROM agent.schema_migrations), 0)
         = $latest_version;" | grep -qx 't'
    exit 0
fi

elapsed=0
until database_is_ready; do
    if [ "$elapsed" -ge "$WAIT_SECONDS" ]; then
        echo "PostgreSQL 준비를 ${WAIT_SECONDS}초 동안 기다렸지만 연결할 수 없습니다." >&2
        exit 1
    fi
    sleep 1
    elapsed=$((elapsed + 1))
done

runner_sql="$(mktemp)"
trap 'rm -f "$runner_sql"' EXIT HUP INT TERM

{
    printf '\\set ON_ERROR_STOP on\n'
    printf "SELECT pg_advisory_lock(%s);\n" "$LOCK_KEY"

    for migration_path in "$MIGRATION_DIR"/[0-9][0-9][0-9][0-9]_*.sql; do
        migration_name="$(basename "$migration_path")"
        version_prefix="${migration_name%%_*}"
        version="$(printf '%s' "$version_prefix" | sed 's/^0*//')"
        version="${version:-0}"

        if [ "$version" -eq 1 ]; then
            printf "SELECT to_regclass('agent.schema_migrations') IS NULL AS should_apply \\gset\n"
        else
            printf "SELECT NOT EXISTS (SELECT 1 FROM agent.schema_migrations WHERE version = %s) AS should_apply \\gset\n" "$version"
        fi

        printf '\\if :should_apply\n'
        printf '\\echo Applying migration %s\n' "$migration_name"
        printf '\\ir %s\n' "$migration_path"
        printf '\\else\n'
        printf '\\echo Skipping applied migration %s\n' "$migration_name"
        printf '\\endif\n'
        printf "DO \$migration_check\$ BEGIN IF NOT EXISTS (SELECT 1 FROM agent.schema_migrations WHERE version = %s) THEN RAISE EXCEPTION 'Migration %s did not record schema_migrations version %s'; END IF; END \$migration_check\$;\n" "$version" "$migration_name" "$version"
    done

    printf "DO \$migration_compat\$ BEGIN IF COALESCE((SELECT max(version) FROM agent.schema_migrations), 0) <> %s THEN RAISE EXCEPTION 'Database schema version is newer than the available Migration files'; END IF; END \$migration_compat\$;\n" "$latest_version"
    printf "SELECT pg_advisory_unlock(%s);\n" "$LOCK_KEY"
} > "$runner_sql"

run_psql -X -v ON_ERROR_STOP=1 -f "$runner_sql"
echo "Agent DB Migration 확인 완료: version $latest_version"
