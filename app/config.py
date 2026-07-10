"""Agent API 환경 설정 스키마와 로딩 진입점.

환경변수 접근은 이 모듈에만 두며 실제 Secret 조회 방식은 구현 단계에서 연결한다.
"""

from pydantic import BaseModel, Field


class Settings(BaseModel):
    """애플리케이션과 외부 연결에 필요한 환경 설정."""

    app_name: str = Field(default="Bambi Agent API", description="애플리케이션 이름")
    app_version: str = Field(default="0.1.0", description="애플리케이션 버전")
    environment: str = Field(default="local", description="실행 환경 이름")
    agent_database_url: str | None = Field(
        default=None, description="Agent DB 연결 문자열"
    )
    vector_store_url: str | None = Field(
        default=None, description="Vector 저장소 연결 문자열"
    )
    queue_url: str | None = Field(default=None, description="Job Queue 연결 문자열")
    openai_api_key: str | None = Field(
        default=None, description="OpenAI Secret 참조 값"
    )
    tavily_api_key: str | None = Field(
        default=None, description="Tavily Secret 참조 값"
    )
    naver_client_id: str | None = Field(default=None, description="Naver API Client ID")
    naver_client_secret: str | None = Field(
        default=None, description="Naver API Client Secret"
    )
    news_api_key: str | None = Field(default=None, description="NewsAPI Secret 참조 값")
    gdelt_base_url: str | None = Field(default=None, description="GDELT API 기본 URL")


def load_settings() -> Settings:
    """[SYS-003] 환경변수와 Secret 참조로부터 설정을 로딩한다."""
    raise NotImplementedError("[SYS-003] 환경 설정 로딩 구현이 필요합니다.")
