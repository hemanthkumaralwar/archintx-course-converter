"""Tests for converter/config.py: Settings, load_settings and validate_config."""

import os

import pytest

from converter import config
from converter.config import DEFAULT_GEMINI_MODEL, Settings, load_settings
from converter.exceptions import ConfigurationError

KEY = "AIza-test-key-not-real"


def env_file(tmp_path, text):
    path = tmp_path / ".env"
    path.write_text(text, encoding="utf-8")
    return path


def test_defaults_when_nothing_is_set():
    assert load_settings(environ={}, env_file=None) == Settings()
    assert Settings().llm_provider == "gemini"
    assert Settings().gemini_model == DEFAULT_GEMINI_MODEL


def test_values_from_env_file(tmp_path):
    path = env_file(tmp_path, f"LLM_PROVIDER=gemini\nGEMINI_API_KEY={KEY}\nGEMINI_MODEL=m-1\n")

    settings = load_settings(environ={}, env_file=path)

    assert (settings.gemini_api_key, settings.gemini_model) == (KEY, "m-1")


def test_environment_wins_over_env_file(tmp_path):
    path = env_file(tmp_path, "GEMINI_MODEL=from-file\nGEMINI_API_KEY=file-key\n")

    settings = load_settings(environ={"GEMINI_MODEL": "from-env"}, env_file=path)

    assert (settings.gemini_model, settings.gemini_api_key) == ("from-env", "file-key")


def test_values_are_trimmed_and_blank_means_missing(tmp_path):
    environ = {"LLM_PROVIDER": "  Gemini ", "GEMINI_API_KEY": "   ", "GEMINI_MODEL": ""}

    settings = load_settings(environ=environ, env_file=None)

    assert settings == Settings(llm_provider="gemini", gemini_api_key="")


def test_missing_env_file_is_fine(tmp_path):
    assert load_settings(environ={}, env_file=tmp_path / "absent.env") == Settings()


def test_key_without_value_in_env_file(tmp_path):
    assert load_settings(environ={}, env_file=env_file(tmp_path, "GEMINI_API_KEY\n")) == Settings()


def test_loading_does_not_change_the_process_environment(tmp_path, monkeypatch):
    monkeypatch.delenv("GEMINI_MODEL", raising=False)

    load_settings(environ={}, env_file=env_file(tmp_path, "GEMINI_MODEL=leak\n"))

    assert "GEMINI_MODEL" not in os.environ


def test_repr_never_shows_the_key():
    settings = Settings(gemini_api_key=KEY)

    assert KEY not in repr(settings)
    assert KEY not in str(settings)


def test_validate_config_passes_for_the_project():
    config.validate_config()


def test_validate_config_reports_a_broken_constant(monkeypatch):
    monkeypatch.setattr(config, "MAX_RETRIES", 0)

    with pytest.raises(ConfigurationError, match="MAX_RETRIES must be at least 1"):
        config.validate_config()


def test_validate_config_reports_a_missing_schema(monkeypatch, tmp_path):
    monkeypatch.setattr(config, "SCHEMA_FILE", tmp_path / "missing.json")

    with pytest.raises(ConfigurationError, match="Schema file not found"):
        config.validate_config()
