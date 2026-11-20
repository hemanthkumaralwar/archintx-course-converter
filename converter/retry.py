"""
retry.py

WHAT: One reusable retry loop for every LLM step (outline, details, modules).

WHY:  The model sometimes returns invalid JSON, breaks a rule, or a request
      fails. Retrying with the previous problems listed in the prompt often
      fixes the result. Writing the loop once means every step gets the same
      behaviour.
"""

import time

from .config import MAX_RETRIES, RETRY_DELAY_SECONDS
from .exceptions import GenerationError, ValidationFailedError

# Only failures that a new attempt can fix are retried. Anything else (a bug
# such as KeyError, or a ConfigurationError) is raised at once with its
# traceback, because retrying it would only spend API quota.
RETRYABLE_ERRORS = (GenerationError, ValidationFailedError)


def run_with_retries(
    label,
    attempt_fn,
    max_attempts=MAX_RETRIES,
    base_delay_seconds=RETRY_DELAY_SECONDS,
    sleep=time.sleep,
):
    """
    WHAT: Call attempt_fn until it succeeds or the attempts run out.

    HOW:  attempt_fn(previous_errors, attempt_number) is called each time.
          If it raises a retryable error, its errors (or the exception text)
          become previous_errors for the next attempt. The wait grows with
          each attempt to ease rate limits.

    WHY:  The function receives the errors as an argument, not from shared
          state, so each attempt starts clean. `sleep` is a parameter so tests
          can run without waiting.

    RETURNS:
        Whatever attempt_fn returns on success.

    RAISES:
        GenerationError: after the last retryable failure.
        Any other exception from attempt_fn, unchanged, on its first occurrence.
    """
    if max_attempts < 1:
        raise ValueError(f"max_attempts must be at least 1 (got {max_attempts}).")

    previous_errors = []

    for attempt_number in range(1, max_attempts + 1):
        try:
            return attempt_fn(previous_errors, attempt_number)

        except RETRYABLE_ERRORS as exc:
            # TODO(team): use logging + progress callback instead — see PLAN.md §6.4 Step 6b
            print(f"{label}: attempt {attempt_number}/{max_attempts} failed: {exc}")

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

            sleep(base_delay_seconds * attempt_number)

    # Unreachable: the last attempt either returns or raises above.
    raise AssertionError("retry loop ended without returning or raising")  # pragma: no cover
