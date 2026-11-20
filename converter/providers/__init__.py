"""
providers

WHAT: LLM providers and get_provider(), which picks one from the settings.

WHY:  Only this module knows which provider classes exist. The rest of the
      code receives an object with generate_json (see base.LLMProvider), so
      switching LLM_PROVIDER in .env needs no code change.
"""

from ..exceptions import ConfigurationError
from .base import LLMProvider
from .gemini import GeminiProvider


def get_provider(settings, api_key=None) -> LLMProvider:
    """
    WHAT: Create the provider named by settings.llm_provider.

    PARAMETERS:
        settings: a config.Settings object.
        api_key:  optional key that replaces the one in settings, for example
                  a key pasted into the web page for a single job.

    RAISES:
        ConfigurationError: if the provider is unknown or its API key is missing.
                            The message names the setting, never a key value.
    """
    factory = PROVIDER_FACTORIES.get(settings.llm_provider)

    if factory is None:
        supported = ", ".join(sorted(PROVIDER_FACTORIES))
        raise ConfigurationError(
            f"LLM_PROVIDER '{settings.llm_provider}' is not supported. Use one of: {supported}."
        )

    return factory(settings, api_key)


def _gemini(settings, api_key):
    key = (api_key or settings.gemini_api_key or "").strip()

    if not key:
        raise ConfigurationError("GEMINI_API_KEY is missing. Add it to your .env file.")

    return GeminiProvider(key, settings.gemini_model, settings.temperature)


# One entry per LLM_PROVIDER value. Step 7 adds "openai".
PROVIDER_FACTORIES = {
    "gemini": _gemini,
}
