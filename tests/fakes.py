"""Test doubles shared by several test files."""


class FakeProvider:
    """
    An LLM provider that returns prepared answers instead of calling an API.

    `answers` is a list; each call takes the next one. An answer that is an
    exception is raised instead of returned. Every call is recorded in `calls`
    as (prompt, schema, label), so tests can check what was sent.
    """

    def __init__(self, answers):
        self.answers = list(answers)
        self.calls = []

    def generate_json(self, prompt, schema, label):
        self.calls.append((prompt, schema, label))

        if not self.answers:
            raise AssertionError(f"FakeProvider has no answer left for: {label}")

        answer = self.answers.pop(0)

        if isinstance(answer, Exception):
            raise answer

        return answer
