"""FastAPI 애플리케이션 팩토리의 기본 조립 결과를 검증한다."""

from fastapi import FastAPI

from app.config import Settings
from app.main import create_app


def test_create_app_uses_settings_metadata() -> None:
    """앱 팩토리가 전달된 이름과 버전을 FastAPI Metadata에 반영하는지 검증한다."""
    application = create_app(Settings(app_name="Test Agent API", app_version="9.9.9"))

    assert isinstance(application, FastAPI)
    assert application.title == "Test Agent API"
    assert application.version == "9.9.9"
