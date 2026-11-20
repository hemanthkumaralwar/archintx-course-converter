"""
Tests for converter/providers/openai.py, with a stand-in for the OpenAI client.

No live call is made: the project has no OpenAI key (₹0 budget). The stand-in
records exactly what would be sent, so the request shape is still checked.
"""

import copy
import json
from types import SimpleNamespace

import pytest

from converter.config import Settings, load_settings
from converter.exceptions import ConfigurationError, GenerationError
from converter.planner import generate_plan
from converter.prompts import plan_schema
from converter.providers import get_provider
from converter.providers.base import LLMProvider
from converter.providers.openai import WRAPPER_KEY, OpenAIProvider, to_strict_schema
from converter.user_input import make_request
from tests.sample_course import SCHEMAS, plan_answer

KEY = "sk-test-key-not-real"


class StubCompletions:
    """Stands in for client.chat.completions: records each request, returns or raises."""

    def __init__(self, outcome):
        self.outcome = outcome
        self.requests = []

    def create(self, **request):
        self.requests.append(request)
        if isinstance(self.outcome, Exception):
            raise self.outcome
        return self.outcome


def completion(content=None, refusal=None, finish_reason="stop"):
    message = SimpleNamespace(content=content, refusal=refusal)
    return SimpleNamespace(choices=[SimpleNamespace(message=message, finish_reason=finish_reason)])


def openai_with(outcome):
    completions = StubCompletions(outcome)
    client = SimpleNamespace(chat=SimpleNamespace(completions=completions))
    return OpenAIProvider(KEY, "model-o", 0.3, client=client), completions


def object_nodes(node):
    """Every schema node that describes an object, at any depth."""
    if isinstance(node, list):
        for item in node:
            yield from object_nodes(item)
    elif isinstance(node, dict):
        if node.get("type") == "object" or "properties" in node:
            yield node
        for key, value in node.items():
            values = value.values() if key == "properties" else [value]
            for child in values:
                yield from object_nodes(child)


# ---------------------------------------------------------------------------
# Strict schema conversion
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "schema",
    [SCHEMAS.lesson_request, SCHEMAS.overview_request, SCHEMAS.details_request, plan_schema()],
    ids=["lesson", "overview", "details", "plan"],
)
def test_every_object_is_closed_and_requires_all_properties(schema):
    strict, wrapped = to_strict_schema(schema)
    nodes = list(object_nodes(strict))

    assert not wrapped
    assert len(nodes) > 1
    for node in nodes:
        assert node["additionalProperties"] is False
        assert node["required"] == list(node["properties"])


def test_lesson_fields_keep_their_names_and_dollar_schema_is_dropped():
    strict, _ = to_strict_schema(SCHEMAS.details_request)
    lesson, _ = to_strict_schema(SCHEMAS.lesson_request)

    assert "$schema" in SCHEMAS.details_request
    assert "$schema" not in json.dumps(strict)
    assert list(lesson["properties"]) == list(SCHEMAS.lesson_request["properties"])
    assert "title" in lesson["properties"]  # a field called "title", not the keyword


def test_conversion_does_not_change_the_input():
    original = copy.deepcopy(SCHEMAS.lesson_request)

    to_strict_schema(SCHEMAS.lesson_request)

    assert SCHEMAS.lesson_request == original


@pytest.mark.parametrize("field", ["quiz", "title"])
def test_non_object_schema_is_wrapped(field):
    section_schema = SCHEMAS.lesson_request["properties"][field]

    strict, wrapped = to_strict_schema(section_schema)

    assert wrapped
    assert strict["required"] == [WRAPPER_KEY]
    assert strict["additionalProperties"] is False
    assert strict["properties"][WRAPPER_KEY]["type"] == section_schema["type"]


def test_object_without_listed_properties_is_closed():
    assert to_strict_schema({"type": "object"}) == (
        {"type": "object", "properties": {}, "required": [], "additionalProperties": False},
        False,
    )


# ---------------------------------------------------------------------------
# Requests and answers
# ---------------------------------------------------------------------------


def test_request_uses_strict_json_schema_output():
    provider, completions = openai_with(completion(json.dumps({"ok": True})))

    assert provider.generate_json("Write it", plan_schema(), "testing") == {"ok": True}

    request = completions.requests[0]
    assert (request["model"], request["temperature"]) == ("model-o", 0.3)
    assert request["messages"] == [{"role": "user", "content": "Write it"}]
    assert request["response_format"]["type"] == "json_schema"
    assert request["response_format"]["json_schema"]["strict"] is True
    assert request["response_format"]["json_schema"]["schema"] == to_strict_schema(plan_schema())[0]


def test_wrapped_answer_is_unwrapped():
    quiz_schema = SCHEMAS.lesson_request["properties"]["quiz"]
    provider, _ = openai_with(completion(json.dumps({WRAPPER_KEY: [{"question": "Q"}]})))

    assert provider.generate_json("Fix the quiz", quiz_schema, "repairing") == [{"question": "Q"}]


@pytest.mark.parametrize(
    ("outcome", "message"),
    [
        (completion(refusal="I can't help with that"), "refused to answer while testing"),
        (completion(content=""), "empty answer while testing"),
        (completion(content=None), "empty answer while testing"),
        (SimpleNamespace(choices=[]), "no answer while testing"),
        (completion(content='{"cut', finish_reason="length"), "cut off at its length limit"),
        (completion(content="{not json"), "not valid JSON while testing"),
        (RuntimeError("429 rate limited"), "API call failed while testing: 429 rate limited"),
    ],
    ids=["refusal", "empty", "none", "no-choices", "cut-off", "bad-json", "api-error"],
)
def test_failures_become_generation_errors(outcome, message):
    provider, _ = openai_with(outcome)

    with pytest.raises(GenerationError, match=message):
        provider.generate_json("prompt", plan_schema(), "testing")


def test_refusal_text_is_not_repeated():
    provider, _ = openai_with(completion(refusal="Quoting the private document"))

    with pytest.raises(GenerationError) as error:
        provider.generate_json("prompt", plan_schema(), "testing")

    assert "private document" not in str(error.value)


def test_wrapped_answer_without_the_wrapper_key():
    provider, _ = openai_with(completion(json.dumps({"other": 1})))

    with pytest.raises(GenerationError, match="missing 'value'"):
        provider.generate_json("prompt", {"type": "string"}, "testing")


def test_api_error_text_never_contains_the_key():
    provider, _ = openai_with(RuntimeError(f"Incorrect API key provided: {KEY}"))

    with pytest.raises(GenerationError) as error:
        provider.generate_json("prompt", plan_schema(), "testing")

    assert KEY not in str(error.value)
    assert "[redacted]" in str(error.value)


def test_client_creation_failure_hides_the_key(monkeypatch):
    def refuse(api_key):
        raise ValueError(f"bad key {api_key}")

    monkeypatch.setattr("converter.providers.openai.openai.OpenAI", refuse)

    with pytest.raises(ConfigurationError) as error:
        get_provider(Settings(llm_provider="openai", openai_api_key=KEY))

    assert KEY not in str(error.value)


# ---------------------------------------------------------------------------
# Choosing OpenAI through the settings
# ---------------------------------------------------------------------------


def test_openai_is_chosen_with_llm_provider():
    settings = load_settings(
        environ={"LLM_PROVIDER": "openai", "OPENAI_API_KEY": KEY, "OPENAI_MODEL": "model-o"},
        env_file=None,
    )

    provider = get_provider(settings)

    assert isinstance(provider, OpenAIProvider)
    assert isinstance(provider, LLMProvider)
    assert provider.model == "model-o"
    assert KEY not in repr(settings)


def test_openai_without_its_key_names_the_variable():
    settings = Settings(llm_provider="openai", gemini_api_key="a-gemini-key")

    with pytest.raises(ConfigurationError, match="OPENAI_API_KEY is missing"):
        get_provider(settings)


def test_planner_works_through_the_openai_provider():
    provider, completions = openai_with(completion(json.dumps(plan_answer())))
    request = make_request("Spike", "beginner", 2, lessons_per_module=2)

    modules = generate_plan(provider, request)

    assert [module["title"] for module in modules] == ["Module 1", "Module 2"]
    assert len(completions.requests) == 1
