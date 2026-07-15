#!/bin/sh
# 빈 Agent DB에 Migration을 적용하고 선택적으로 개발 Seed를 최초 한 번 주입한다.

set -eu

PGHOST="${PGHOST:-/var/run/postgresql}"
PGDATABASE="${PGDATABASE:-${POSTGRES_DB:-postgres}}"
PGUSER="${PGUSER:-${POSTGRES_USER:-postgres}}"
PGPASSWORD="${PGPASSWORD:-${POSTGRES_PASSWORD:-}}"
export PGHOST PGDATABASE PGUSER PGPASSWORD

/bin/sh /usr/local/bin/run-agent-db-migrations

if [ "${AGENT_DB_APPLY_DEV_SEEDS:-true}" != "true" ]; then
    echo "Agent DB 개발 Seed 적용을 건너뜁니다."
    exit 0
fi

for seed_path in /opt/bambi/seeds/[0-9][0-9][0-9][0-9]_*.sql; do
    if [ ! -f "$seed_path" ]; then
        echo "개발 Seed 파일이 없습니다: /opt/bambi/seeds"
        exit 0
    fi
    echo "Applying development seed $(basename "$seed_path")"
    psql -X -v ON_ERROR_STOP=1 -f "$seed_path"
done

echo "Agent DB 개발 Seed 적용 완료"
