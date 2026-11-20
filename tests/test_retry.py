"""Tests for converter.retry.run_with_retries."""

import pytest

from converter.exceptions import ConfigurationError, GenerationError, ValidationFailedError
from converter.retry import run_with_retries


class Recorder:
    """Attempt function that raises the given outcomes in order, then returns "ok"."""

    def __init__(self, *outcomes):
        self.outcomes = list(outcomes)
        self.calls = []

    def __call__(self, previous_errors, attempt_number):
        self.calls.append((list(previous_errors), attempt_number))
        if self.outcomes:
            raise self.outcomes.pop(0)
        return "ok"


@pytest.fixture
def waits():
    return []


def run(attempt, waits, max_attempts=3):
    return run_with_retries("Step", attempt, max_attempts, 2, sleep=waits.append)


def test_success_first_time_does_not_wait(waits):
    attempt = Recorder()

    assert run(attempt, waits) == "ok"
    assert attempt.calls == [([], 1)]
    assert waits == []


def test_validation_errors_are_passed_to_next_attempt(waits):
    attempt = Recorder(ValidationFailedError("bad", errors=["quiz/0: wrong", "title: empty"]))

    assert run(attempt, waits) == "ok"
    assert attempt.calls == [([], 1), (["quiz/0: wrong", "title: empty"], 2)]


def test_generation_error_message_is_passed_to_next_attempt(waits):
    attempt = Recorder(GenerationError("empty response"))

    assert run(attempt, waits) == "ok"
    assert attempt.calls[1] == (["empty response"], 2)


def test_validation_error_without_list_uses_message(waits):
    attempt = Recorder(ValidationFailedError("not an object"))

    run(attempt, waits)

    assert attempt.calls[1][0] == ["not an object"]


def test_wait_doubles_after_each_api_failure(waits):
    attempt = Recorder(GenerationError("a"), GenerationError("b"), GenerationError("c"))

    run(attempt, waits, max_attempts=4)

    assert waits == [2, 4, 8]


def test_validation_failure_is_retried_without_waiting(waits):
    attempt = Recorder(ValidationFailedError("bad", errors=["x"]), GenerationError("503"))

    run(attempt, waits)

    assert waits == [4]  # only the API failure (attempt 2) waits


def test_gives_up_after_last_attempt(waits):
    attempt = Recorder(*[GenerationError(f"fail {n}") for n in range(3)])

    with pytest.raises(GenerationError, match="failed after 3 attempts. Last error: fail 2"):
        run(attempt, waits)

    assert len(attempt.calls) == 3
    assert waits == [2, 4]  # no wait after the final attempt


@pytest.mark.parametrize("error", [KeyError("lessons"), TypeError("bad"), ConfigurationError("x")])
def test_non_retryable_error_is_raised_after_one_call(waits, error):
    attempt = Recorder(error)

    with pytest.raises(type(error)):
        run(attempt, waits)

    assert len(attempt.calls) == 1
    assert waits == []


def test_single_attempt_allowed(waits):
    attempt = Recorder(GenerationError("once"))

    with pytest.raises(GenerationError, match="after 1 attempts"):
        run(attempt, waits, max_attempts=1)


def test_zero_attempts_rejected(waits):
    with pytest.raises(ValueError, match="at least 1"):
        run(Recorder(), waits, max_attempts=0)
