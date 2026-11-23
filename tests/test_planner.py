"""Tests for converter/planner.py: course size, the document outline, and the title-based plan."""

import logging

import pytest

from converter.chunking import Section
from converter.exceptions import ConfigurationError, ValidationFailedError
from converter.planner import (
    MAX_COURSE_HOURS,
    MAX_LESSONS_PER_MODULE,
    CourseSize,
    SizeRequest,
    auto_course_size,
    check_course_size,
    check_size_request,
    generate_course_details,
    generate_outline,
    resolve_course_size,
    validate_outline,
    validate_plan,
)
from converter.user_input import make_request
from tests.fakes import FakeProvider
from tests.sample_course import SCHEMAS, details_answer, plan_answer


@pytest.fixture
def request_2x2(tmp_path):
    return make_request("Spike", "beginner", 2, lessons_per_module=2, output_root=tmp_path)


@pytest.fixture(autouse=True)
def no_waiting(monkeypatch):
    monkeypatch.setattr("converter.retry.time.sleep", lambda seconds: None)


def plan_errors(data, request):
    with pytest.raises(ValidationFailedError) as error:
        validate_plan(data, request)
    return error.value.errors


def test_valid_plan_is_cleaned(request_2x2):
    plan = plan_answer()
    plan["modules"][0]["title"] = "  Module 1  "
    plan["modules"][0]["lessons"][0] = " Lesson 1.1 "

    modules = validate_plan(plan, request_2x2)

    assert modules[0] == {"title": "Module 1", "lessons": ["Lesson 1.1", "Lesson 1.2"]}


@pytest.mark.parametrize("data", [[], {"modules": "x"}, None])
def test_plan_must_be_an_object_with_modules(data, request_2x2):
    assert plan_errors(data, request_2x2) == ['top-level value must be {"modules": [...]}']


def test_plan_problems_are_all_reported(request_2x2):
    plan = {
        "modules": [
            "not an object",
            {"title": " ", "lessons": ["A"]},
            {"title": "M3", "lessons": ["Same", "Same"]},
            {"title": "M4", "lessons": ["", "B"]},
        ]
    }

    assert plan_errors(plan, request_2x2) == [
        "expected 2 modules, got 4",
        "module 1 is not an object",
        "module 2 has no title",
        "module 2 must have exactly 2 lesson titles (got 1)",
        "module 3 has duplicate lesson titles",
        "module 4 lesson 1 is empty",
    ]


def test_missing_lesson_list(request_2x2):
    plan = plan_answer()
    del plan["modules"][1]["lessons"]

    assert plan_errors(plan, request_2x2) == [
        "module 2 must have exactly 2 lesson titles (got no list)"
    ]


def test_course_details_are_retried_until_they_are_an_object(request_2x2):
    provider = FakeProvider(["not an object", details_answer()])

    details = generate_course_details(provider, request_2x2, SCHEMAS)

    assert details["course"]["modules"] == []
    assert "top-level value is not an object" in provider.calls[1][0]  # fed back to the model


def test_course_details_with_invalid_modules_are_rejected(request_2x2):
    answer = details_answer()
    answer["course"]["modules"] = [{"left": "over"}]
    provider = FakeProvider([answer, details_answer()])

    assert generate_course_details(provider, request_2x2, SCHEMAS)["course"]["modules"] == []
    assert len(provider.calls) == 2


# ---------------------------------------------------------------------------
# Course size for the converter
# ---------------------------------------------------------------------------


def sections_of(*lengths):
    return [Section(f"s{n}", (f"Part {n}",), "x" * length) for n, length in enumerate(lengths, 1)]


@pytest.mark.parametrize(
    ("characters", "expected"),
    [
        (100, CourseSize(1, 2)),  # very short: the minimum of 2 lessons
        (6000, CourseSize(1, 2)),  # exactly 2 lessons' worth
        (6001, CourseSize(1, 3)),
        (24_000, CourseSize(1, 8)),  # 8 lessons still fit in one module
        (27_000, CourseSize(2, 5)),  # 9 lessons: 2 modules, spread evenly
        (50_000, CourseSize(3, 6)),  # 17 lessons
        (1_000_000, CourseSize(8, 8)),  # capped at 64 lessons
    ],
)
def test_auto_course_size(characters, expected):
    size = auto_course_size(sections_of(characters))

    assert size == expected
    assert 1 <= size.lessons_per_module <= MAX_LESSONS_PER_MODULE
    assert size.modules * size.lessons_per_module <= 64


def test_auto_size_counts_every_section():
    assert auto_course_size(sections_of(3000, 3000, 3000)) == CourseSize(1, 3)


@pytest.mark.parametrize(
    "size",
    [CourseSize(0, 3), CourseSize(31, 3), CourseSize(2, 0), CourseSize(2, 9), CourseSize(2, 2.5)],
)
def test_requested_size_out_of_range(size):
    with pytest.raises(ConfigurationError, match="must be from 1 to"):
        check_course_size(size)


def test_requested_size_in_range():
    check_course_size(CourseSize(30, 8))


# ---------------------------------------------------------------------------
# Size choices: modules, lessons per module and hours, each optional
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("request_", "expected"),
    [
        (SizeRequest(2, 3), CourseSize(2, 3)),  # both counts: exactly those
        (SizeRequest(hours=3), CourseSize(1, 6)),  # 6 lessons, fewest modules
        (SizeRequest(hours=5), CourseSize(2, 5)),  # 10 lessons spread over 2 modules
        (SizeRequest(modules=2, hours=3), CourseSize(2, 3)),
        (SizeRequest(modules=4, hours=3), CourseSize(4, 2)),  # rounded up: never shorter
        (SizeRequest(lessons_per_module=4, hours=3), CourseSize(2, 4)),
        (SizeRequest(modules=1, hours=32), CourseSize(1, 8)),  # capped at 8 lessons
        (SizeRequest(hours=MAX_COURSE_HOURS), CourseSize(8, 8)),
    ],
)
def test_size_from_choices_without_the_document(request_, expected):
    assert resolve_course_size(request_) == expected
    assert resolve_course_size(request_, sections_of(100)) == expected  # document not used


@pytest.mark.parametrize(
    ("request_", "expected"),
    [
        (None, CourseSize(3, 6)),  # 17 lessons from 50,000 characters
        (SizeRequest(), CourseSize(3, 6)),
        (SizeRequest(modules=2), CourseSize(2, 8)),  # 17 / 2 = 9, capped at 8
        (SizeRequest(modules=6), CourseSize(6, 3)),
        (SizeRequest(lessons_per_module=4), CourseSize(5, 4)),
    ],
)
def test_size_from_the_document_fills_what_is_automatic(request_, expected):
    assert resolve_course_size(request_, sections_of(50_000)) == expected


def test_size_that_needs_the_document_is_unknown_without_it():
    assert resolve_course_size(SizeRequest(modules=2)) is None
    assert resolve_course_size(None) is None


def test_course_size_is_used_as_it_is():
    assert resolve_course_size(CourseSize(30, 8), sections_of(100)) == CourseSize(30, 8)


def test_size_choices_cannot_all_be_set():
    with pytest.raises(ConfigurationError, match="not all three"):
        check_size_request(SizeRequest(2, 3, 3))


@pytest.mark.parametrize(
    ("request_", "message"),
    [
        (SizeRequest(hours=0), "course hours must be from 1 to 32"),
        (SizeRequest(hours=33), "course hours must be from 1 to 32"),
        (SizeRequest(modules=31), "modules must be from 1 to 30"),
        (SizeRequest(lessons_per_module=9), "lessons per module must be from 1 to 8"),
    ],
)
def test_size_choices_out_of_range(request_, message):
    with pytest.raises(ConfigurationError, match=message):
        resolve_course_size(request_)


def test_pieces_count_every_ai_step():
    assert CourseSize(2, 3).pieces == 10  # outline, details, 2 overviews, 6 lessons


# ---------------------------------------------------------------------------
# Outline from a document
# ---------------------------------------------------------------------------

SECTIONS = sections_of(500, 500, 500)
SIZE = CourseSize(1, 2)


def outline(lessons=None, **changes):
    data = {
        "courseTitle": "Python Basics",
        "level": "beginner",
        "modules": [
            {
                "title": "Getting started",
                "lessons": lessons
                or [
                    {"title": "Variables", "sections": ["s1"]},
                    {"title": "Loops", "sections": ["s2", "s3"]},
                ],
            }
        ],
    }
    data.update(changes)
    return data


def outline_errors(data, size=SIZE):
    with pytest.raises(ValidationFailedError) as error:
        validate_outline(data, size, {"s1", "s2", "s3"})
    return error.value.errors


def test_outline_is_returned_cleaned():
    data = outline(
        lessons=[
            {"title": " Variables ", "sections": ["s1", "s1", "s2"]},
            {"title": "Loops", "sections": ["s3"]},
        ],
        courseTitle="  Python Basics ",
    )

    result = generate_outline(FakeProvider([data]), SECTIONS, SIZE)

    assert result == {
        "courseTitle": "Python Basics",
        "level": "beginner",
        "modules": [
            {
                "title": "Getting started",
                "lessons": [
                    {"title": "Variables", "sections": ["s1", "s2"]},
                    {"title": "Loops", "sections": ["s3"]},
                ],
            }
        ],
    }


def test_unknown_section_ids_are_rejected_and_retried():
    wrong = outline(
        lessons=[
            {"title": "Variables", "sections": ["s1", "s99"]},
            {"title": "Loops", "sections": ["s2"]},
        ]
    )
    provider = FakeProvider([wrong, outline()])

    assert generate_outline(provider, SECTIONS, SIZE) == outline()
    assert len(provider.calls) == 2
    second_prompt = provider.calls[1][0]
    assert "module 1 lesson 1 cites sections that do not exist: s99" in second_prompt


def test_outline_problems_are_all_reported():
    data = outline(
        lessons=[
            {"title": "Same", "sections": []},
            {"title": "same", "sections": "s1"},
        ],
        courseTitle=" ",
        level="expert",
    )
    data["modules"].append("not an object")

    assert outline_errors(data) == [
        "courseTitle is empty",
        "level must be one of: beginner, intermediate, advanced",
        "expected 1 modules, got 2",
        "module 1 lesson 1 must cite at least one section",
        "module 1 lesson 2 must cite at least one section",
        "module 1 has duplicate lesson titles",
        "module 2 is not an object",
    ]


def test_outline_lesson_shape_problems():
    data = outline(lessons=["not an object", {"title": "", "sections": ["s1"]}])

    assert outline_errors(data) == [
        "module 1 lesson 1 is not an object",
        "module 1 lesson 2 has no title",
    ]


def test_outline_module_with_wrong_lesson_count():
    data = outline(lessons=[{"title": "Only one", "sections": ["s1"]}])
    data["modules"][0]["title"] = ""

    assert outline_errors(data) == [
        "module 1 has no title",
        "module 1 must have exactly 2 lessons (got 1)",
    ]


@pytest.mark.parametrize("data", [None, [], {"modules": "x"}])
def test_outline_must_be_an_object_with_modules(data):
    assert outline_errors(data) == [
        'top-level value must be {"courseTitle": ..., "level": ..., "modules": [...]}'
    ]


def test_outline_needs_sections():
    with pytest.raises(ValueError, match="at least one section"):
        generate_outline(FakeProvider([]), [], SIZE)


def test_outline_rejects_a_size_out_of_range():
    with pytest.raises(ConfigurationError):
        generate_outline(FakeProvider([]), SECTIONS, CourseSize(1, 20))


def test_outline_log_has_counts_but_no_titles(caplog):
    with caplog.at_level(logging.INFO, logger="converter.planner"):
        generate_outline(FakeProvider([outline()]), SECTIONS, SIZE)

    assert "Outline: 1 modules x 2 lessons; 3 of 3 sections cited" in caplog.text
    assert "Python Basics" not in caplog.text
