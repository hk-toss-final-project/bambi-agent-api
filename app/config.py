"""Agent API 환경 설정 스키마와 환경변수 로딩 기능."""

import os

from dotenv import load_dotenv
from pydantic import BaseModel, ConfigDict, Field, SecretStr


class Settings(BaseModel):
    """애플리케이션과 외부 연결에 필요한 환경 설정."""

    model_config = ConfigDict(frozen=True)

    app_name: str = Field(default="Bambi Agent API", description="애플리케이션 이름")
    app_version: str = Field(default="0.1.0", description="애플리케이션 버전")
    environment: str = Field(default="local", description="실행 환경 이름")
    api_prefix: str = Field(default="/internal/v1", description="내부 API 경로 Prefix")
    docs_enabled: bool = Field(default=True, description="OpenAPI 문서 활성화 여부")
    agent_database_url: str | None = Field(
        default=None, description="Agent DB 연결 문자열"
    )
    vector_store_url: str | None = Field(
        default=None, description="Vector 저장소 연결 문자열"
    )
    queue_url: str | None = Field(default=None, description="Job Queue 연결 문자열")
    openai_api_key: SecretStr | None = Field(
        default=None, description="OpenAI Secret 참조 값"
    )
    tavily_api_key: SecretStr | None = Field(
        default=None, description="Tavily Secret 참조 값"
    )
    naver_client_id: str | None = Field(default=None, description="Naver API Client ID")
    naver_client_secret: SecretStr | None = Field(
        default=None, description="Naver API Client Secret"
    )
    news_api_key: SecretStr | None = Field(
        default=None, description="NewsAPI Secret 참조 값"
    )
    gdelt_base_url: str | None = Field(default=None, description="GDELT API 기본 URL")


def _optional_env(name: str) -> str | None:
    """빈 문자열을 제외한 선택 환경변수 값을 반환한다."""
    value = os.getenv(name)
    return value if value else None


def _boolean_env(name: str, default: bool) -> bool:
    """환경변수의 일반적인 참·거짓 문자열을 bool로 변환한다."""
    value = os.getenv(name)
    if value is None:
        return default
    return value.strip().lower() in {"1", "true", "yes", "on"}


def load_settings() -> Settings:
    """[SYS-003] 환경변수와 Secret 참조로부터 설정을 로딩한다."""
    load_dotenv()
    return Settings(
        app_name=os.getenv("APP_NAME", "Bambi Agent API"),
        app_version=os.getenv("APP_VERSION", "0.1.0"),
        environment=os.getenv("APP_ENV", "local"),
        api_prefix=os.getenv("API_PREFIX", "/internal/v1"),
        docs_enabled=_boolean_env("DOCS_ENABLED", True),
        agent_database_url=_optional_env("AGENT_DATABASE_URL"),
        vector_store_url=_optional_env("VECTOR_STORE_URL"),
        queue_url=_optional_env("QUEUE_URL"),
        openai_api_key=_optional_env("OPENAI_API_KEY"),
        tavily_api_key=_optional_env("TAVILY_API_KEY"),
        naver_client_id=_optional_env("NAVER_CLIENT_ID"),
        naver_client_secret=_optional_env("NAVER_CLIENT_SECRET"),
        news_api_key=_optional_env("NEWS_API_KEY"),
        gdelt_base_url=_optional_env("GDELT_BASE_URL"),
    )
