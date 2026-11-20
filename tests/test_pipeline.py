"""
Tests for converter/pipeline.py and the generator entry point, using FakeProvider.

The fake answers are real content from samples/javascript-beginner.json, so every
schema and content check runs exactly as it does with Gemini. No network is used.
"""

import copy
import json
import logging
import socket

import pytest

from converter import generate
from converter.exceptions import CheckpointError, ConfigurationError, GenerationError
from converter.json_utils import load_json
from converter.pipeline import Progress, run_pipeline, total_pieces
from converter.user_input import make_request
from converter.validation import collect_errors
from tests.fakes import FakeProvider
from tests.sample_course import (
    LESSONS,
    SCHEMAS,
    details_answer,
    lesson_answer,
    overview_answer,
    plan_answer,
)


def all_answers():
    """Answers in the order the pipeline asks for them, for 2 modules x 2 lessons."""
    return [
        plan_answer(),
        details_answer(),
        overview_answer(0),
        lesson_answer(0),
        lesson_answer(1),
        overview_answer(1),
        lesson_answer(2),
        lesson_answer(3),
    ]


ALL_LABELS = [
    "planning the course",
    "creating course details",
    "writing the overview for module 1",
    "writing module 1, lesson 1",
    "writing module 1, lesson 2",
    "writing the overview for module 2",
    "writing module 2, lesson 1",
    "writing module 2, lesson 2",
]


@pytest.fixture
def request_2x2(tmp_path):
    # 2 hours, 2 lessons of 30 planned minutes per module: 2 modules.
    return make_request("Spike", "beginner", 2, lessons_per_module=2, output_root=tmp_path)


@pytest.fixture(autouse=True)
def no_network(monkeypatch):
    """Fail any test that tries to open a network connection."""

    def refuse(*args, **kwargs):
        raise AssertionError("tests must not use the network")

    monkeypatch.setattr(socket.socket, "connect", refuse)


@pytest.fixture(autouse=True)
def no_waiting(monkeypatch):
    monkeypatch.setattr("converter.retry.time.sleep", lambda seconds: None)


def labels(provider):
    return [label for _, _, label in provider.calls]


# ---------------------------------------------------------------------------
# A full run
# ---------------------------------------------------------------------------


def test_full_run_writes_a_valid_course(request_2x2):
    provider = FakeProvider(all_answers())
    events = []

    output_file = run_pipeline(request_2x2, provider, events.append)

    course = load_json(output_file)
    assert collect_errors(SCHEMAS.course_validator, course) == []
    assert labels(provider) == ALL_LABELS

    modules = course["course"]["modules"]
    assert course["course"]["courseId"] == "spike-beginner-v1"
    assert course["course"]["totalDuration"] == "2 hours"
    assert [module["moduleId"] for module in modules] == [
        "spike-beginner-v1-mod-1",
        "spike-beginner-v1-mod-2",
    ]
    assert [lesson["lessonId"] for lesson in modules[1]["lessons"]] == [
        "spike-beginner-v1-mod-2-lesson-1",
        "spike-beginner-v1-mod-2-lesson-2",
    ]

    assert total_pieces(request_2x2) == 8
    assert events == [
        Progress(1, 8, "Course plan"),
        Progress(2, 8, "Course details"),
        Progress(3, 8, "Module 1 overview: Module 1"),
        Progress(4, 8, "Lesson 1.1: Lesson 1.1"),
        Progress(5, 8, "Lesson 1.2: Lesson 1.2"),
        Progress(6, 8, "Module 2 overview: Module 2"),
        Progress(7, 8, "Lesson 2.1: Lesson 2.1"),
        Progress(8, 8, "Lesson 2.2: Lesson 2.2"),
    ]


def test_progress_callback_is_optional(request_2x2):
    assert run_pipeline(request_2x2, FakeProvider(all_answers())).is_file()


# ---------------------------------------------------------------------------
# Stopping and resuming
# ---------------------------------------------------------------------------


def test_resume_after_crash_continues_without_repeating_calls(request_2x2):
    answers = all_answers()
    first = FakeProvider(answers[:5])  # runs out while writing module 2's overview

    with pytest.raises(AssertionError, match="no answer left"):
        run_pipeline(request_2x2, first)

    second = FakeProvider(answers[5:])
    events = []
    run_pipeline(request_2x2, second, events.append)

    assert labels(second) == ALL_LABELS[5:]
    assert [event.reused for event in events] == [True] * 5 + [False] * 3
    assert events[-1].done == events[-1].total == 8


def test_finished_course_rerun_makes_no_calls(request_2x2):
    run_pipeline(request_2x2, FakeProvider(all_answers()))
    again = FakeProvider([])

    run_pipeline(request_2x2, again)

    assert again.calls == []


def test_plan_for_a_different_course_size_is_not_reused(request_2x2, tmp_path):
    first = FakeProvider(all_answers()[:2])
    with pytest.raises(AssertionError):
        run_pipeline(request_2x2, first)

    bigger = make_request("Spike", "beginner", 2, lessons_per_module=1, output_root=tmp_path)

    with pytest.raises(CheckpointError, match="number of lessons per module"):
        run_pipeline(bigger, FakeProvider([]))


def test_output_without_plan_is_refused(request_2x2):
    request_2x2.output_dir.mkdir(parents=True)
    request_2x2.output_file.write_text("{}", encoding="utf-8")

    with pytest.raises(CheckpointError, match="exists without its plan"):
        run_pipeline(request_2x2, FakeProvider([]))


# ---------------------------------------------------------------------------
# Repairs and retries
# ---------------------------------------------------------------------------


def test_one_broken_section_is_repaired_with_a_small_request(request_2x2):
    broken = lesson_answer(0)
    good_quiz = broken["quiz"]
    broken["quiz"] = copy.deepcopy(good_quiz)
    broken["quiz"][0]["correctAnswer"] = "9"
    answers = all_answers()
    answers[3:4] = [broken, good_quiz]
    provider = FakeProvider(answers)

    run_pipeline(request_2x2, provider)

    assert labels(provider)[3:5] == ["writing module 1, lesson 1", "repairing the quiz field"]


def test_rejected_lesson_is_saved_retried_and_logged_without_its_text(request_2x2, caplog):
    broken = lesson_answer(0)
    broken["title"] = "Lesson 1: SECRET-DOCUMENT-TEXT"  # title rule
    broken["quiz"][0]["correctAnswer"] = "9"  # quiz rule: two fields, so no single repair
    answers = all_answers()
    answers[3:3] = [broken]
    provider = FakeProvider(answers)

    with caplog.at_level(logging.INFO):
        run_pipeline(request_2x2, provider)

    assert labels(provider)[3:5] == ["writing module 1, lesson 1"] * 2
    assert "Module 1, lesson 1: attempt 1/3 failed: 2 validation problem(s)" in caplog.text
    assert "SECRET-DOCUMENT-TEXT" not in caplog.text

    saved = json.loads(
        (request_2x2.error_dir / "module_1_lesson_1_attempt_1.json").read_text("utf-8")
    )
    assert saved["errors"][0].startswith("quiz 1 correctAnswer")


def test_logs_never_contain_course_text(request_2x2, caplog):
    with caplog.at_level(logging.DEBUG):
        run_pipeline(request_2x2, FakeProvider(all_answers()))

    assert "Planning 2 modules x 2 lessons" in caplog.text
    assert LESSONS[0]["title"] not in caplog.text
    assert "Lesson 1.1" not in caplog.text


def test_api_failure_after_all_attempts_stops_the_run(request_2x2):
    failure = GenerationError("Gemini API call failed while planning the course: 503")
    provider = FakeProvider([failure] * 3)

    with pytest.raises(GenerationError, match="failed after 3 attempts"):
        run_pipeline(request_2x2, provider)


# ---------------------------------------------------------------------------
# The command-line entry point
# ---------------------------------------------------------------------------


@pytest.fixture
def cli(monkeypatch, request_2x2):
    """Run generate.main with a fixed request and a fake provider."""

    def run(provider):
        monkeypatch.setattr(generate, "read_course_request", lambda argv: request_2x2)
        monkeypatch.setattr(generate, "get_provider", lambda settings: provider)
        return generate.main([])

    return run


def test_cli_prints_progress_and_succeeds(cli, capsys, request_2x2):
    assert cli(FakeProvider(all_answers())) == 0

    out = capsys.readouterr().out
    assert "[1/8] Course plan (saved)" in out
    assert "[8/8] Lesson 2.2: Lesson 2.2 (saved)" in out
    assert str(request_2x2.output_file) in out


def test_cli_reports_expected_errors_briefly(cli, capsys, monkeypatch):
    def missing_key(settings):
        raise ConfigurationError("GEMINI_API_KEY is missing.")

    monkeypatch.setattr(generate, "read_course_request", lambda argv: None)
    monkeypatch.setattr(generate, "get_provider", missing_key)

    assert generate.main([]) == 1
    assert "ERROR: GEMINI_API_KEY is missing." in capsys.readouterr().err


def test_cli_ctrl_c_keeps_progress(cli, capsys):
    assert cli(FakeProvider([KeyboardInterrupt()])) == 130
    assert "Interrupted" in capsys.readouterr().err
