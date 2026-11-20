"""Tests for converter/user_input.py: validating a course request and reading it from the CLI."""

import pytest

from converter.config import LESSONS_PER_MODULE, OUTPUT_ROOT
from converter.exceptions import ConfigurationError
from converter.user_input import make_request, read_course_request, slugify


def test_defaults_and_derived_values():
    request = make_request("  AI Engineer: Beginner ", " Beginner ", "31")

    assert (request.title, request.difficulty, request.duration_hours) == (
        "AI Engineer: Beginner",
        "beginner",
        31.0,
    )
    assert (request.lessons_per_module, request.output_root) == (LESSONS_PER_MODULE, OUTPUT_ROOT)
    assert request.module_count == 8  # 1860 minutes / (8 lessons x 30 minutes), rounded up
    assert request.course_id == "ai-engineer-beginner-beginner-v1"
    assert (request.level_display, request.total_duration_text) == ("Beginner", "31 hours")
    assert request.output_file == OUTPUT_ROOT / "ai_engineer_beginner" / "ai_engineer_beginner.json"
    assert request.as_dict()["lessons_per_module"] == LESSONS_PER_MODULE


def test_course_size_and_folder_can_be_chosen(tmp_path):
    request = make_request("Spike", "advanced", 2, lessons_per_module=2, output_root=tmp_path)

    assert (request.module_count, request.plan_file) == (2, tmp_path / "spike" / "spike_plan.json")


def test_course_id_override():
    assert make_request("x", "beginner", 8, course_id=" my-id ").course_id == "my-id"
    assert make_request("x", "beginner", 8, course_id="   ").course_id == "x-beginner-v1"


@pytest.mark.parametrize(
    ("args", "message"),
    [
        (("", "beginner", 8), "title cannot be empty"),
        (("x" * 121, "beginner", 8), "too long"),
        (("!!!", "beginner", 8), "at least one letter or digit"),
        (("x", "expert", 8), "Difficulty must be one of"),
        (("x", "beginner", "ten"), "must be a number of hours"),
        (("x", "beginner", "nan"), "positive number of hours"),
        (("x", "beginner", -1), "positive number of hours"),
        (("x", "beginner", 1), "gives 1 modules"),
        (("x", "beginner", 1000), "gives 250 modules"),
    ],
)
def test_invalid_requests(args, message):
    with pytest.raises(ConfigurationError, match=message):
        make_request(*args)


@pytest.mark.parametrize("lessons", [0, 2.5, "2"])
def test_invalid_lessons_per_module(lessons):
    with pytest.raises(ConfigurationError, match="Lessons per module"):
        make_request("x", "beginner", 8, lessons_per_module=lessons)


def test_slugify():
    assert slugify("AI Engineer: Beginner!") == "ai_engineer_beginner"


def test_flags_skip_the_questions(monkeypatch):
    monkeypatch.setattr("builtins.input", lambda question: pytest.fail("should not ask"))

    request = read_course_request(["--title", "Py", "--difficulty", "beginner", "--duration", "8"])

    assert (request.title, request.module_count) == ("Py", 2)


def test_missing_values_are_asked_for(monkeypatch):
    answers = iter(["Beginner", "8"])
    monkeypatch.setattr("builtins.input", lambda question: next(answers))

    assert read_course_request(["--title", "Py"]).difficulty == "beginner"


def test_no_input_available(monkeypatch):
    def closed(question):
        raise EOFError

    monkeypatch.setattr("builtins.input", closed)

    with pytest.raises(ConfigurationError, match="No input available"):
        read_course_request([])
