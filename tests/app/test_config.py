"""환경변수 기반 Agent API 설정 로딩을 검증한다."""

from pytest import MonkeyPatch

from app.config import load_settings


def test_load_settings_reads_environment(monkeypatch: MonkeyPatch) -> None:
    """환경변수와 Secret이 Settings 타입으로 변환되는지 검증한다."""
    monkeypatch.setenv("APP_NAME", "Environment Agent API")
    monkeypatch.setenv("APP_VERSION", "2.0.0")
    monkeypatch.setenv("APP_ENV", "production")
    monkeypatch.setenv("API_PREFIX", "/agent/internal/v1")
    monkeypatch.setenv("DOCS_ENABLED", "false")
    monkeypatch.setenv("OPENAI_API_KEY", "test-secret")

    settings = load_settings()

    assert settings.app_name == "Environment Agent API"
    assert settings.app_version == "2.0.0"
    assert settings.environment == "production"
    assert settings.api_prefix == "/agent/internal/v1"
    assert settings.docs_enabled is False
    assert settings.openai_api_key is not None
    assert settings.openai_api_key.get_secret_value() == "test-secret"
