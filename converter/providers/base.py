"""
base.py

WHAT: The interface every LLM provider implements.

WHY:  The planner and lesson writer depend only on this one method, not on any
      SDK, so Gemini, OpenAI (Step 7) and the tests' fake provider are
      interchangeable. A Protocol is used instead of a base class because the
      providers share no code; each only needs the same method.
"""

from typing import Protocol, runtime_checkable


# runtime_checkable lets tests confirm that each provider has the method.
@runtime_checkable
class LLMProvider(Protocol):
    """Sends one prompt and returns the model's answer as parsed JSON."""

    def generate_json(self, prompt: str, schema: dict, label: str) -> object:
        """
        WHAT: Ask the model for JSON that follows `schema`.

        PARAMETERS:
            prompt: the instruction text.
            schema: the JSON Schema the answer must follow.
            label:  what the call is for, such as "writing module 1, lesson 2";
                    used only in error messages.

        RETURNS:
            The parsed JSON (a dict, list, or other value).

        RAISES:
            GenerationError: if the call fails or the answer is not valid JSON.
                             The message must never contain an API key.
        """
        ...
