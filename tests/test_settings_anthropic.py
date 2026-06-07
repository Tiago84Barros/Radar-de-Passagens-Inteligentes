def test_anthropic_api_key_loaded_from_env(monkeypatch):
    from app.settings import get_settings

    monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-ant-test-123")
    get_settings.cache_clear()
    try:
        settings = get_settings()
        assert settings.anthropic_api_key == "sk-ant-test-123"
    finally:
        get_settings.cache_clear()


def test_anthropic_api_key_defaults_to_none(monkeypatch):
    from app.settings import get_settings

    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    get_settings.cache_clear()
    try:
        settings = get_settings()
        assert settings.anthropic_api_key is None
    finally:
        get_settings.cache_clear()
