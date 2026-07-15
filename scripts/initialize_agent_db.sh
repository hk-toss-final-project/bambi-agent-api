#!/bin/sh
# Agent DB 시작 시 Migration을 적용하고 변경된 개발 Seed를 한 번 주입한다.

set -eu

PGHOST="${PGHOST:-/var/run/postgresql}"
PGDATABASE="${PGDATABASE:-${POSTGRES_DB:-postgres}}"
PGUSER="${PGUSER:-${POSTGRES_USER:-postgres}}"
PGPASSWORD="${PGPASSWORD:-${POSTGRES_PASSWORD:-}}"
export PGHOST PGDATABASE PGUSER PGPASSWORD

MODE="${1:-}"
SEED_DIR="${AGENT_DB_SEED_DIR:-/opt/bambi/seeds}"
SEED_STATE_PATH="${AGENT_DB_SEED_STATE_PATH:-${PGDATA:-/var/lib/postgresql/data}/.bambi-dev-seed-sha256}"

seed_checksum() {
    for seed_path in "$SEED_DIR"/[0-9][0-9][0-9][0-9]_*.sql; do
        sha256sum "$seed_path"
    done | sha256sum | awk '{print $1}'
}

/bin/sh /usr/local/bin/run-agent-db-migrations "$MODE"

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
    [ -f "$SEED_STATE_PATH" ] && [ "$(cat "$SEED_STATE_PATH")" = "$expected_checksum" ]
    exit $?
fi

seed_lock_path="${SEED_STATE_PATH}.lock"
(
    flock -x 9

    if [ -f "$SEED_STATE_PATH" ] && [ "$(cat "$SEED_STATE_PATH")" = "$expected_checksum" ]; then
        echo "Agent DB 개발 Seed가 이미 적용됐습니다."
        exit 0
    fi

    for seed_path in "$SEED_DIR"/[0-9][0-9][0-9][0-9]_*.sql; do
        echo "Applying development seed $(basename "$seed_path")"
        psql -X -v ON_ERROR_STOP=1 -f "$seed_path"
    done

    seed_state_tmp="${SEED_STATE_PATH}.tmp.$$"
    printf '%s\n' "$expected_checksum" > "$seed_state_tmp"
    mv "$seed_state_tmp" "$SEED_STATE_PATH"
) 9>"$seed_lock_path"

echo "Agent DB 개발 Seed 적용 완료"
