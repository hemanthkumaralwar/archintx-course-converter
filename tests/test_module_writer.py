"""Tests for converter/module_writer.py: overview and lesson writing, repairs and rejections."""

import json

import pytest

from converter.exceptions import GenerationError
from converter.module_writer import repair_section, write_lesson, write_overview
from converter.user_input import make_request
from tests.fakes import FakeProvider
from tests.sample_course import SCHEMAS, details_answer, lesson_answer, overview_answer, plan_answer


@pytest.fixture
def request_2x2(tmp_path):
    request = make_request("Spike", "beginner", 2, lessons_per_module=2, output_root=tmp_path)
    request.error_dir.mkdir(parents=True)
    return request


@pytest.fixture(autouse=True)
def no_waiting(monkeypatch):
    monkeypatch.setattr("converter.retry.time.sleep", lambda seconds: None)


def overview(provider, request):
    return write_overview(provider, request, 0, plan_answer()["modules"], details_answer(), SCHEMAS)


def lesson(provider, request):
    return write_lesson(
        provider,
        request,
        0,
        0,
        plan_answer()["modules"],
        overview_answer(0),
        details_answer(),
        SCHEMAS,
    )


def rejected(request, name):
    return json.loads((request.error_dir / name).read_text("utf-8"))


def test_overview_is_retried_until_valid_and_rejects_are_saved(request_2x2):
    bad_shape = overview_answer(0)
    del bad_shape["title"]
    provider = FakeProvider(["not an object", bad_shape, overview_answer(0)])

    assert overview(provider, request_2x2)["title"] == overview_answer(0)["title"]
    assert len(provider.calls) == 3
    assert rejected(request_2x2, "module_1_overview_attempt_2.json")["errors"] == [
        "(root): 'title' is a required property"
    ]


def test_overview_gives_up_after_three_attempts(request_2x2):
    with pytest.raises(GenerationError, match="Module 1 overview failed after 3 attempts"):
        overview(FakeProvider(["x", "x", "x"]), request_2x2)


def test_lesson_that_is_not_an_object_is_retried(request_2x2):
    provider = FakeProvider([["a list"], lesson_answer(0)])

    assert lesson(provider, request_2x2)["title"] == lesson_answer(0)["title"]


def test_lesson_failing_only_the_schema_is_saved_and_retried(request_2x2):
    too_many_cards = lesson_answer(0)
    too_many_cards["useCaseCards"].append(too_many_cards["useCaseCards"][0])
    provider = FakeProvider([too_many_cards, lesson_answer(0)])

    lesson(provider, request_2x2)

    errors = rejected(request_2x2, "module_1_lesson_1_attempt_1.json")["errors"]
    assert errors and errors[0].startswith("useCaseCards")


def test_repair_that_does_not_fix_the_section_stops_after_two_rounds(request_2x2):
    broken = lesson_answer(0)
    broken["quiz"][0]["correctAnswer"] = "9"
    still_broken = broken["quiz"]
    provider = FakeProvider([broken, still_broken, still_broken, lesson_answer(0)])

    lesson(provider, request_2x2)

    labels = [label for _, _, label in provider.calls]
    assert labels == [
        "writing module 1, lesson 1",
        "repairing the quiz field",
        "repairing the quiz field",
        "writing module 1, lesson 1",
    ]


def test_repair_of_a_field_the_schema_does_not_have_is_skipped(request_2x2):
    assert repair_section(FakeProvider([]), request_2x2, {}, "unknown", ["x"], SCHEMAS) is None
