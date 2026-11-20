"""Tests for converter/providers: get_provider, GeminiProvider and the provider interface."""

import json
from types import SimpleNamespace

import pytest

from converter.config import Settings
from converter.exceptions import ConfigurationError, GenerationError
from converter.planner import generate_plan
from converter.providers import get_provider
from converter.providers.base import LLMProvider
from converter.providers.gemini import GeminiProvider
from converter.user_input import make_request
from tests.fakes import FakeProvider

KEY = "AIza-test-key-not-real"
SCHEMA = {"type": "object"}


class StubModels:
    """Stands in for the Gemini SDK's client.models: returns or raises what it is given."""

    def __init__(self, outcome):
        self.outcome = outcome
        self.requests = []

    def generate_content(self, model, contents, config):
        self.requests.append({"model": model, "contents": contents, "config": config})
        if isinstance(self.outcome, Exception):
            raise self.outcome
        return SimpleNamespace(text=self.outcome)


def gemini_with(outcome):
    models = StubModels(outcome)
    provider = GeminiProvider(KEY, "model-x", 0.3, client=SimpleNamespace(models=models))
    return provider, models


# ---------------------------------------------------------------------------
# get_provider
# ---------------------------------------------------------------------------


def test_gemini_is_chosen_from_settings():
    provider = get_provider(Settings(gemini_api_key=KEY, gemini_model="model-x"))

    assert isinstance(provider, GeminiProvider)
    assert (provider.model, provider.temperature) == ("model-x", 0.3)


def test_unknown_provider_is_rejected():
    with pytest.raises(ConfigurationError, match="LLM_PROVIDER 'claude' is not supported"):
        get_provider(Settings(llm_provider="claude", gemini_api_key=KEY))


@pytest.mark.parametrize("key", ["", "   "])
def test_missing_key_names_the_variable(key):
    with pytest.raises(ConfigurationError, match="GEMINI_API_KEY is missing"):
        get_provider(Settings(gemini_api_key=key))


def test_key_passed_in_replaces_the_settings_key():
    provider = get_provider(Settings(gemini_api_key=""), api_key=" pasted-key ")

    assert provider._api_key == "pasted-key"


def test_providers_follow_the_interface():
    assert isinstance(get_provider(Settings(gemini_api_key=KEY)), LLMProvider)
    assert isinstance(FakeProvider([]), LLMProvider)


def test_client_creation_failure_hides_the_key(monkeypatch):
    def refuse(api_key):
        raise ValueError(f"bad key {api_key}")

    monkeypatch.setattr("converter.providers.gemini.genai.Client", refuse)

    with pytest.raises(ConfigurationError) as error:
        get_provider(Settings(gemini_api_key=KEY))

    assert KEY not in str(error.value)
    assert "[redacted]" in str(error.value)


# ---------------------------------------------------------------------------
# GeminiProvider
# ---------------------------------------------------------------------------


def test_returns_parsed_json_and_sends_settings():
    provider, models = gemini_with(json.dumps({"ok": True}))

    assert provider.generate_json("Write it", SCHEMA, "testing") == {"ok": True}

    request = models.requests[0]
    assert (request["model"], request["contents"]) == ("model-x", "Write it")
    assert request["config"].response_json_schema == SCHEMA
    assert request["config"].response_mime_type == "application/json"
    assert request["config"].temperature == 0.3


@pytest.mark.parametrize(
    ("outcome", "message"),
    [
        (None, "empty response while testing"),
        ("", "empty response while testing"),
        ("{not json", "not valid JSON while testing"),
        (RuntimeError("503 overloaded"), "API call failed while testing: 503 overloaded"),
    ],
    ids=["none", "empty", "bad-json", "api-error"],
)
def test_failures_become_generation_errors(outcome, message):
    provider, _ = gemini_with(outcome)

    with pytest.raises(GenerationError, match=message):
        provider.generate_json("prompt", SCHEMA, "testing")


def test_api_error_text_never_contains_the_key():
    provider, _ = gemini_with(RuntimeError(f"401 for https://x.example/?key={KEY}"))

    with pytest.raises(GenerationError) as error:
        provider.generate_json("prompt", SCHEMA, "testing")

    assert KEY not in str(error.value)
    assert "key=[redacted]" in str(error.value)


# ---------------------------------------------------------------------------
# The planner uses whatever provider it is given
# ---------------------------------------------------------------------------


def test_planner_works_with_a_fake_provider():
    request = make_request("Spike", "beginner", 8)  # 2 modules of 8 lessons
    plan = {
        "modules": [
            {"title": f"Module {m}", "lessons": [f"Lesson {m}.{n}" for n in range(1, 9)]}
            for m in (1, 2)
        ]
    }
    provider = FakeProvider([plan])

    modules = generate_plan(provider, request)

    assert [module["title"] for module in modules] == ["Module 1", "Module 2"]
    assert provider.calls[0][2] == "planning the course"
