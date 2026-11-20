"""
openai.py

WHAT: The OpenAI provider (optional, paid): the only module that talks to the
      OpenAI SDK. Chosen with LLM_PROVIDER=openai.

WHY:  OpenAI's structured output ("strict" JSON-schema mode) needs a stricter
      schema than Gemini: every object must list all its properties as
      required and forbid extra ones, and the top level must be an object.
      to_strict_schema() converts our schemas, so the rest of the code sends
      the same schemas to either provider.
"""

import json

import openai

from ..exceptions import ConfigurationError, GenerationError
from .base import redact

# Schema keywords OpenAI's strict mode does not accept. Our request schemas
# contain no other unsupported keyword (counts are removed for every provider
# in schema_utils); the full schema is still checked after every answer.
DROPPED_KEYWORDS = frozenset({"$schema"})

# A repair request asks for one lesson field, which can be a list or text.
# Strict mode needs an object at the top, so such a schema is wrapped as
# {"value": ...} and the answer is unwrapped again.
WRAPPER_KEY = "value"


def to_strict_schema(schema):
    """
    WHAT: Convert one of our JSON Schemas to OpenAI strict-mode form.

    RETURNS:
        (strict_schema, wrapped): wrapped is True when the original top level
        was not an object and the answer must be read from WRAPPER_KEY.
        The input schema is not changed.
    """
    converted = _strict_node(schema)

    if converted.get("type") == "object":
        return converted, False

    wrapper = {
        "type": "object",
        "properties": {WRAPPER_KEY: converted},
        "required": [WRAPPER_KEY],
        "additionalProperties": False,
    }
    return wrapper, True


def _strict_node(node):
    """Return a converted copy of one schema node (dicts and lists are walked)."""
    if isinstance(node, list):
        return [_strict_node(item) for item in node]

    if not isinstance(node, dict):
        return node

    result = {}

    for key, value in node.items():
        if key in DROPPED_KEYWORDS:
            continue

        if key == "properties":
            # Keys here are field names (one is even called "title"), not
            # schema keywords, so only their values are converted.
            result[key] = {name: _strict_node(sub) for name, sub in value.items()}
        else:
            result[key] = _strict_node(value)

    if result.get("type") == "object" or "properties" in result:
        properties = result.setdefault("properties", {})
        result["required"] = list(properties)
        result["additionalProperties"] = False

    return result


class OpenAIProvider:
    """
    WHAT: Sends strict JSON-schema requests to OpenAI and returns parsed JSON.

    WHY:  `client` can be passed in so tests can use a stand-in with the same
          `chat.completions.create` method instead of the network.
    """

    def __init__(self, api_key, model, temperature, client=None):
        self.model = model
        self.temperature = temperature
        # Kept only to remove the key from any error text before it is shown.
        self._api_key = api_key
        self._client = client if client is not None else _create_client(api_key)

    def generate_json(self, prompt, schema, label):
        """
        WHAT: Send a prompt with a strict response schema and return the parsed JSON.

        RAISES:
            GenerationError: if the API call fails, the model refuses, the
                             answer is cut off or empty, or it is not valid JSON.
        """
        strict_schema, wrapped = to_strict_schema(schema)

        try:
            response = self._client.chat.completions.create(
                model=self.model,
                temperature=self.temperature,
                messages=[{"role": "user", "content": prompt}],
                response_format={
                    "type": "json_schema",
                    "json_schema": {"name": "response", "strict": True, "schema": strict_schema},
                },
            )
        except Exception as exc:
            # The SDK raises many exception types; one type keeps retries simple.
            raise GenerationError(
                f"OpenAI API call failed while {label}: {redact(exc, self._api_key)}"
            ) from exc

        data = _parse_answer(response, label)

        if not wrapped:
            return data

        if not isinstance(data, dict) or WRAPPER_KEY not in data:
            raise GenerationError(f"OpenAI answer is missing '{WRAPPER_KEY}' while {label}.")

        return data[WRAPPER_KEY]


def _parse_answer(response, label):
    """
    WHAT: Return the parsed JSON from a chat completion.

    WHY:  A refusal's text is not included in the error, because errors are
          logged and the refusal could quote the user's document.
    """
    choices = getattr(response, "choices", None)

    if not choices:
        raise GenerationError(f"OpenAI returned no answer while {label}.")

    choice = choices[0]

    if getattr(choice.message, "refusal", None):
        raise GenerationError(f"OpenAI refused to answer while {label}.")

    if choice.finish_reason == "length":
        raise GenerationError(f"OpenAI's answer was cut off at its length limit while {label}.")

    text = choice.message.content

    if not text:
        raise GenerationError(f"OpenAI returned an empty answer while {label}.")

    try:
        return json.loads(text)
    except json.JSONDecodeError as exc:
        raise GenerationError(
            f"OpenAI returned text that is not valid JSON while {label}: {exc.msg}"
        ) from exc


def _create_client(api_key):
    """
    RAISES:
        ConfigurationError: if the SDK refuses to create a client.
    """
    try:
        return openai.OpenAI(api_key=api_key)
    except Exception as exc:
        raise ConfigurationError(
            f"Could not create the OpenAI client: {redact(exc, api_key)}"
        ) from exc
