#!/bin/sh
# Agent DB를 실행하고 새 Migration과 개발 Seed를 반영한 뒤 상태를 검증한다.

set -eu

SCRIPT_DIR="$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)"
PROJECT_ROOT="$(CDPATH= cd -- "$SCRIPT_DIR/.." && pwd)"
AGENT_DB_HEALTH_MAX_ATTEMPTS="${AGENT_DB_HEALTH_MAX_ATTEMPTS:-60}"
AGENT_DB_HEALTH_POLL_SECONDS="${AGENT_DB_HEALTH_POLL_SECONDS:-1}"

cd "$PROJECT_ROOT"

docker compose up -d agent-db
docker compose exec -T -u postgres agent-db \
    /bin/sh /usr/local/bin/initialize-agent-db

AGENT_DB_CONTAINER_ID="$(docker compose ps -q agent-db)"
if [ -z "$AGENT_DB_CONTAINER_ID" ]; then
    echo "Agent DB 컨테이너를 찾을 수 없습니다." >&2
    exit 1
fi

agent_db_health_attempt=1
agent_db_health_status="unknown"
while [ "$agent_db_health_attempt" -le "$AGENT_DB_HEALTH_MAX_ATTEMPTS" ]; do
    agent_db_health_status="$(
        docker inspect --format '{{if .State.Health}}{{.State.Health.Status}}{{else}}{{.State.Status}}{{end}}' \
            "$AGENT_DB_CONTAINER_ID"
    )"
    if [ "$agent_db_health_status" = "healthy" ]; then
        echo "Agent DB Health Check 통과"
        exit 0
    fi

    if [ "$agent_db_health_status" != "starting" ] \
        && [ "$agent_db_health_status" != "unhealthy" ]; then
        echo "Agent DB 컨테이너 상태가 비정상입니다: $agent_db_health_status" >&2
        exit 1
    fi

    if [ "$agent_db_health_attempt" -lt "$AGENT_DB_HEALTH_MAX_ATTEMPTS" ]; then
        sleep "$AGENT_DB_HEALTH_POLL_SECONDS"
    fi
    agent_db_health_attempt=$((agent_db_health_attempt + 1))
done

echo "Agent DB Health Check가 제한 시간 안에 통과하지 못했습니다: $agent_db_health_status" >&2
exit 1
