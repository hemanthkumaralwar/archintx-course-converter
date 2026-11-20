"""Test doubles shared by several test files."""


class FakeProvider:
    """
    An LLM provider that returns prepared answers instead of calling an API.

    `answers` is a list; each call takes the next one. An answer that is an
    exception (including KeyboardInterrupt) is raised instead of returned.
    Every call is recorded in `calls` as (prompt, schema, label), so tests
    can check what was sent.
    """

    def __init__(self, answers):
        self.answers = list(answers)
        self.calls = []

    def generate_json(self, prompt, schema, label):
        self.calls.append((prompt, schema, label))

        if not self.answers:
            raise AssertionError(f"FakeProvider has no answer left for: {label}")

        answer = self.answers.pop(0)

        if isinstance(answer, BaseException):
            raise answer

        return answer


# Child-process stand-ins for app.extraction tests. They live here, in a small
# module, because a spawned child process must import them by name.


def slow_reader(path, limits, connection):
    """Never answers in time."""
    import time

    time.sleep(60)


def crashing_reader(path, limits, connection):
    """Dies without answering, like a crash inside the PDF library."""
    import os

    os._exit(1)


def failing_reader(path, limits, connection):
    """Fails with an unexpected error."""
    from app.extraction import read_in_child

    read_in_child(None, limits, connection)
