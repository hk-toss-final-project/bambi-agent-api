#!/bin/sh
# Agent DB 시작 시 Migration을 적용하고 변경된 개발 Seed를 한 번 주입한다.

set -eu

SCRIPT_DIR="$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)"
DATABASE_URL="${AGENT_DATABASE_URL:-}"
PGHOST="${PGHOST:-/var/run/postgresql}"
PGPORT="${PGPORT:-5432}"
PGDATABASE="${PGDATABASE:-${POSTGRES_DB:-postgres}}"
PGUSER="${PGUSER:-${POSTGRES_USER:-postgres}}"
PGPASSWORD="${PGPASSWORD:-${POSTGRES_PASSWORD:-}}"
export PGHOST PGPORT PGDATABASE PGUSER PGPASSWORD

MODE="${1:-}"
SEED_DIR="${AGENT_DB_SEED_DIR:-/opt/bambi/seeds}"
SEED_STATE_PATH="${AGENT_DB_SEED_STATE_PATH:-${PGDATA:-/var/lib/postgresql/data}/.bambi-dev-seed-sha256}"
SEED_STATE_BACKEND="${AGENT_DB_SEED_STATE_BACKEND:-file}"
SEED_LOCK_KEY="764224902"

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

# 배포 환경의 URL 또는 로컬 libpq 환경변수로 psql을 실행한다.
run_psql() {
    if [ -n "$DATABASE_URL" ]; then
        psql -d "$DATABASE_URL" "$@"
        return
    fi

    psql "$@"
}

# Seed 파일명과 내용으로 경로에 독립적인 합성 Checksum을 계산한다.
seed_checksum() {
    for seed_path in "$SEED_DIR"/[0-9][0-9][0-9][0-9]_*.sql; do
        seed_hash="$(sha256sum "$seed_path" | awk '{print $1}')"
        printf '%s  %s\n' "$seed_hash" "$(basename "$seed_path")"
    done | sha256sum | awk '{print $1}'
}

# DB에 기록된 최신 성공 Seed Checksum이 현재 파일과 같은지 확인한다.
database_seed_is_current() {
    run_psql -X -q -t -A -v ON_ERROR_STOP=1 -c "
            SELECT COALESCE(
                (
                    SELECT details ->> 'checksum' = '$expected_checksum'
                    FROM agent.audit_logs
                    WHERE actor_type = 'system'
                      AND actor_id = 'agent-db-initializer'
                      AND action = 'development_seed_applied'
                      AND resource_type = 'development_seed_bundle'
                      AND succeeded
                    ORDER BY created_at DESC, id DESC
                    LIMIT 1
                ),
                false
            );
        " | grep -qx 't'
}

# PostgreSQL Advisory Lock 안에서 변경된 Seed를 적용하고 Checksum 이력을 남긴다.
apply_database_seed() {
    seed_runner_sql="$(mktemp)"
    trap 'rm -f "$seed_runner_sql"' EXIT HUP INT TERM

    {
        printf '\\set ON_ERROR_STOP on\n'
        printf "SELECT pg_advisory_lock(%s);\n" "$SEED_LOCK_KEY"
        printf "SELECT COALESCE((SELECT details ->> 'checksum' = :'seed_checksum' FROM agent.audit_logs WHERE actor_type = 'system' AND actor_id = 'agent-db-initializer' AND action = 'development_seed_applied' AND resource_type = 'development_seed_bundle' AND succeeded ORDER BY created_at DESC, id DESC LIMIT 1), false) AS seed_is_current \\gset\n"
        printf '\\if :seed_is_current\n'
        printf '\\echo Agent DB development seed is already applied.\n'
        printf '\\else\n'

        seed_count=0
        for seed_path in "$SEED_DIR"/[0-9][0-9][0-9][0-9]_*.sql; do
            printf '\\echo Applying development seed %s\n' "$(basename "$seed_path")"
            printf '\\ir %s\n' "$seed_path"
            seed_count=$((seed_count + 1))
        done

        printf "INSERT INTO agent.audit_logs (actor_type, actor_id, action, resource_type, resource_id, succeeded, details) VALUES ('system', 'agent-db-initializer', 'development_seed_applied', 'development_seed_bundle', :'seed_checksum', true, jsonb_build_object('checksum', :'seed_checksum', 'seed_count', %s));\n" "$seed_count"
        printf '\\endif\n'
        printf "SELECT pg_advisory_unlock(%s);\n" "$SEED_LOCK_KEY"
    } > "$seed_runner_sql"

    run_psql -X -v ON_ERROR_STOP=1 \
        -v seed_checksum="$expected_checksum" \
        -f "$seed_runner_sql"
}

migration_runner="$(resolve_migration_runner)"
if [ ! -f "$migration_runner" ]; then
    echo "Migration Runner를 찾을 수 없습니다: $migration_runner" >&2
    exit 1
fi

/bin/sh "$migration_runner" "$MODE"

if [ "${AGENT_DB_APPLY_DEV_SEEDS:-true}" != "true" ]; then
    echo "Agent DB 개발 Seed 적용을 건너뜁니다."
    exit 0
fi

set -- "$SEED_DIR"/[0-9][0-9][0-9][0-9]_*.sql
if [ ! -f "$1" ]; then
    echo "개발 Seed 파일이 없습니다: $SEED_DIR" >&2
    exit 1
fi

expected_checksum="$(seed_checksum)"

if [ "$MODE" = "--check" ]; then
    case "$SEED_STATE_BACKEND" in
        database)
            database_seed_is_current
            ;;
        file)
            [ -f "$SEED_STATE_PATH" ] \
                && [ "$(cat "$SEED_STATE_PATH")" = "$expected_checksum" ]
            ;;
        *)
            echo "지원하지 않는 Seed 상태 저장소입니다: $SEED_STATE_BACKEND" >&2
            exit 1
            ;;
    esac
    exit 0
fi

case "$SEED_STATE_BACKEND" in
    database)
        apply_database_seed
        ;;
    file)
        seed_lock_path="${SEED_STATE_PATH}.lock"
        (
            flock -x 9

            if [ -f "$SEED_STATE_PATH" ] \
                && [ "$(cat "$SEED_STATE_PATH")" = "$expected_checksum" ]; then
                echo "Agent DB 개발 Seed가 이미 적용됐습니다."
                exit 0
            fi

            for seed_path in "$SEED_DIR"/[0-9][0-9][0-9][0-9]_*.sql; do
                echo "Applying development seed $(basename "$seed_path")"
                run_psql -X -v ON_ERROR_STOP=1 -f "$seed_path"
            done

            seed_state_tmp="${SEED_STATE_PATH}.tmp.$$"
            printf '%s\n' "$expected_checksum" > "$seed_state_tmp"
            mv "$seed_state_tmp" "$SEED_STATE_PATH"
        ) 9>"$seed_lock_path"
        ;;
    *)
        echo "지원하지 않는 Seed 상태 저장소입니다: $SEED_STATE_BACKEND" >&2
        exit 1
        ;;
esac

echo "Agent DB 개발 Seed 적용 완료"
