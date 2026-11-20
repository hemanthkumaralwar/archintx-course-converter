"""Tests for converter/module_writer.py: overview and lesson writing, repairs and rejections."""

import json

import pytest

from converter.chunking import Section
from converter.exceptions import GenerationError
from converter.module_writer import repair_section, write_lesson, write_overview
from converter.prompts import DOCUMENT_START, MAX_SOURCE_CHARS, SOURCE_RULES
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


# ---------------------------------------------------------------------------
# Lessons and overviews written from their cited sections (the converter)
# ---------------------------------------------------------------------------


def section(number, text=None):
    return Section(f"s{number}", ("Guide", f"Part {number}"), text or f"SOURCE-TEXT-{number} " * 20)


SECTIONS = [section(1), section(2), section(3)]


def sent_prompt(provider):
    return provider.calls[0][0]


def test_lesson_prompt_contains_its_cited_sections_and_no_others(request_2x2):
    provider = FakeProvider([lesson_answer(0)])

    write_lesson(
        provider,
        request_2x2,
        0,
        0,
        plan_answer()["modules"],
        overview_answer(0),
        details_answer(),
        SCHEMAS,
        source_sections=[SECTIONS[1]],
    )

    prompt = sent_prompt(provider)
    assert "[s2] Guide > Part 2" in prompt
    assert "SOURCE-TEXT-2" in prompt
    assert "SOURCE-TEXT-1" not in prompt and "SOURCE-TEXT-3" not in prompt
    assert prompt.index(SOURCE_RULES.strip()) < prompt.index(DOCUMENT_START + "\n")


def test_overview_prompt_contains_the_module_sections(request_2x2):
    provider = FakeProvider([overview_answer(0)])

    write_overview(
        provider,
        request_2x2,
        0,
        plan_answer()["modules"],
        details_answer(),
        SCHEMAS,
        source_sections=SECTIONS[:2],
    )

    prompt = sent_prompt(provider)
    assert "SOURCE-TEXT-1" in prompt and "SOURCE-TEXT-2" in prompt
    assert "SOURCE-TEXT-3" not in prompt


def test_lesson_prompt_size_is_capped_however_much_is_cited(request_2x2):
    huge = [section(n, "z" * 20_000) for n in (1, 2, 3)]

    def prompt_with(sources):
        provider = FakeProvider([lesson_answer(0)])
        write_lesson(
            provider,
            request_2x2,
            0,
            0,
            plan_answer()["modules"],
            overview_answer(0),
            details_answer(),
            SCHEMAS,
            source_sections=sources,
        )
        return sent_prompt(provider)

    without_source = prompt_with(None)
    with_huge_source = prompt_with(huge)

    added = len(with_huge_source) - len(without_source)
    assert added <= MAX_SOURCE_CHARS + len(SOURCE_RULES) + 200
    assert with_huge_source.count("z" * 100) <= MAX_SOURCE_CHARS // 100
    assert "[s3]" not in with_huge_source  # the cap is reached before the third section


def test_without_sections_the_prompt_has_no_source(request_2x2):
    provider = FakeProvider([lesson_answer(0)])

    lesson(provider, request_2x2)

    assert DOCUMENT_START not in sent_prompt(provider)
    assert SOURCE_RULES.strip() not in sent_prompt(provider)
