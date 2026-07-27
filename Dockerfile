# Report Builder Agent API — 컨테이너 이미지
#
#  · API 와 Worker 가 같은 이미지를 쓴다. 실행 대상은 command 로 가른다.
#      API    : (기본 CMD) uvicorn app.main:app --host 0.0.0.0 --port 8000
#      Worker : python -m workers.main --worker report-generation --loop
#  · uv 로 의존성을 설치한다(AGENTS.md 규칙 5 — pip 직접 사용 금지).
#    uv.lock 을 그대로 쓰는 --frozen 설치라 CI 와 로컬 버전이 어긋나지 않는다.
#  · 의존성 레이어와 소스 레이어를 분리해 소스만 바뀌면 재설치를 건너뛴다.

# ── build stage ── 의존성만 먼저 설치해 레이어 캐시를 태운다
FROM python:3.14-slim AS build

# uv 공식 배포 바이너리 (astral-sh 제공 이미지에서 복사)
COPY --from=ghcr.io/astral-sh/uv:latest /uv /usr/local/bin/uv

ENV UV_COMPILE_BYTECODE=1 \
    UV_LINK_MODE=copy \
    UV_PYTHON_DOWNLOADS=never

WORKDIR /app

# 1) 의존성 레이어 — 매니페스트만 복사해 설치(소스 변경 시 재사용)
COPY pyproject.toml uv.lock ./
RUN uv sync --frozen --no-install-project --no-dev

# 2) 소스 레이어
COPY . .
RUN uv sync --frozen --no-dev

# ── runtime stage ── 빌드 도구 없이 venv + 소스만 담는다
FROM python:3.14-slim AS runtime

# psycopg[binary] 라 libpq 는 휠에 포함되지만, HTTPS 호출(OpenAI·Tavily·Jina)에 CA 번들이 필요하다.
RUN apt-get update \
    && apt-get install -y --no-install-recommends ca-certificates \
    && rm -rf /var/lib/apt/lists/*

# 비루트 실행
RUN useradd --create-home --uid 10001 agent
WORKDIR /app

COPY --from=build --chown=agent:agent /app /app

# pyproject 에 [build-system] 이 없어 uv 가 virtual project 로 다룬다(의존성만 설치, 패키지 설치 X).
# 따라서 app·workers 패키지는 설치본이 아니라 소스 경로로 임포트된다 → PYTHONPATH 를 명시한다.
# (pytest 설정의 pythonpath=["."] 와 같은 전제)
ENV PATH="/app/.venv/bin:$PATH" \
    PYTHONPATH=/app \
    PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1

USER agent
EXPOSE 8000

# 기본은 API. Worker 는 compose 에서 command 로 덮어쓴다.
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]
