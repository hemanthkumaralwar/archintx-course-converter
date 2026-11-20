"""
retry.py

WHAT: One reusable retry loop for every LLM step (outline, details, modules).

WHY:  The model sometimes returns invalid JSON, breaks a rule, or a request
      fails. Retrying with the previous problems listed in the prompt often
      fixes the result. Writing the loop once means every step gets the same
      behaviour.
"""

import logging
import time

from .config import MAX_RETRIES, RETRY_DELAY_SECONDS
from .exceptions import GenerationError, ValidationFailedError

logger = logging.getLogger(__name__)

# Only failures that a new attempt can fix are retried. Anything else (a bug
# such as KeyError, or a ConfigurationError) is raised at once with its
# traceback, because retrying it would only spend API quota.
RETRYABLE_ERRORS = (GenerationError, ValidationFailedError)


def run_with_retries(
    label,
    attempt_fn,
    max_attempts=MAX_RETRIES,
    base_delay_seconds=RETRY_DELAY_SECONDS,
    sleep=None,
):
    """
    WHAT: Call attempt_fn until it succeeds or the attempts run out.

    HOW:  attempt_fn(previous_errors, attempt_number) is called each time.
          If it raises a retryable error, its errors (or the exception text)
          become previous_errors for the next attempt. After an API failure
          (GenerationError, such as Gemini's "503 high demand" or a 429 rate
          limit) the wait doubles each time: base, 2 x base, ... A validation
          failure is retried at once, because waiting cannot fix the answer.

    WHY:  The function receives the errors as an argument, not from shared
          state, so each attempt starts clean. `sleep` defaults to time.sleep,
          looked up at call time, so tests can pass or patch a no-wait version.

    RETURNS:
        Whatever attempt_fn returns on success.

    RAISES:
        GenerationError: after the last retryable failure.
        Any other exception from attempt_fn, unchanged, on its first occurrence.
    """
    if max_attempts < 1:
        raise ValueError(f"max_attempts must be at least 1 (got {max_attempts}).")

    sleep = sleep or time.sleep
    previous_errors = []

    for attempt_number in range(1, max_attempts + 1):
        try:
            return attempt_fn(previous_errors, attempt_number)

        except RETRYABLE_ERRORS as exc:
            logger.warning(
                "%s: attempt %d/%d failed: %s",
                label,
                attempt_number,
                max_attempts,
                describe_failure(exc),
            )

            if attempt_number == max_attempts:
                raise GenerationError(
                    f"{label} failed after {max_attempts} attempts. Last error: {exc}"
                ) from exc

            # Validation failures carry a detailed list; anything else is
            # described by its message.
            if isinstance(exc, ValidationFailedError) and exc.errors:
                previous_errors = list(exc.errors)
            else:
                previous_errors = [str(exc)]

            if not isinstance(exc, ValidationFailedError):
                sleep(base_delay_seconds * 2 ** (attempt_number - 1))

    # Unreachable: the last attempt either returns or raises above.
    raise AssertionError("retry loop ended without returning or raising")  # pragma: no cover


def describe_failure(error):
    """
    WHAT: Describe a failed attempt for the log.

    WHY:  Validation messages quote the model's output, which can contain text
          from the user's document, so only their number is logged. The full
          messages are still sent back to the model and saved in the course's
          errors/ folder. Other failures (API errors) contain no document text.
    """
    if isinstance(error, ValidationFailedError):
        count = len(error.errors) or 1
        return f"{count} validation problem(s); details are in the course's errors folder"

    return str(error)
