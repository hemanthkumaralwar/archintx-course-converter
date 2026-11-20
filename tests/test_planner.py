"""Tests for converter/planner.py: plan validation and the two planning calls."""

import pytest

from converter.exceptions import ValidationFailedError
from converter.planner import generate_course_details, validate_plan
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
