"""
gemini.py

WHAT: The Google Gemini provider: the only module that talks to the Gemini SDK.

WHY:  If the SDK or model changes, only this file changes. Other modules
      receive plain Python data and never see SDK objects.
"""

import json

from google import genai
from google.genai import types

from ..exceptions import ConfigurationError, GenerationError
from .base import redact


class GeminiProvider:
    """
    WHAT: Sends schema-constrained requests to Gemini and returns parsed JSON.

    WHY:  `client` can be passed in so tests can use a stand-in with the same
          `models.generate_content` method instead of the network.
    """

    def __init__(self, api_key, model, temperature, client=None):
        self.model = model
        self.temperature = temperature
        # Kept only to remove the key from any error text before it is shown.
        self._api_key = api_key
        self._client = client if client is not None else _create_client(api_key)

    def generate_json(self, prompt, schema, label):
        """
        WHAT: Send a prompt with a response schema and return the parsed JSON.

        WHY:  response_json_schema makes Gemini follow the schema directly. The
              response is still parsed and checked here, because the network or
              the model can return unusable text.

        RAISES:
            GenerationError: if the API call fails, the response is empty, or
                             the text is not valid JSON.
        """
        try:
            response = self._client.models.generate_content(
                model=self.model,
                contents=prompt,
                config=types.GenerateContentConfig(
                    response_mime_type="application/json",
                    response_json_schema=schema,
                    temperature=self.temperature,
                ),
            )
        except Exception as exc:
            # The SDK can raise many exception types. Wrapping them gives the
            # retry logic one type to handle.
            raise GenerationError(
                f"Gemini API call failed while {label}: {redact(exc, self._api_key)}"
            ) from exc

        text = getattr(response, "text", None)

        if not text:
            raise GenerationError(f"Gemini returned an empty response while {label}.")

        try:
            return json.loads(text)
        except json.JSONDecodeError as exc:
            raise GenerationError(
                f"Gemini returned text that is not valid JSON while {label}: {exc.msg}"
            ) from exc


def _create_client(api_key):
    """
    RAISES:
        ConfigurationError: if the SDK refuses to create a client.
    """
    try:
        return genai.Client(api_key=api_key)
    except Exception as exc:
        raise ConfigurationError(
            f"Could not create the Gemini client: {redact(exc, api_key)}"
        ) from exc
