"""
Tests for converter/convert.py: the whole conversion, with FakeProvider.

The input is the real sample document (samples/inputs/python-basics.txt); the
fake answers are real content from the team's sample course. No network is used.
"""

import shutil
import socket

import pytest

from converter.convert import (
    ConversionOptions,
    convert,
    file_sha256,
    format_minutes,
    job_folder,
    lesson_minutes,
    set_durations,
)
from converter.exceptions import CheckpointError, ExtractionError
from converter.json_utils import load_json
from converter.planner import CourseSize
from converter.validation import collect_errors
from tests.fakes import FakeProvider
from tests.sample_course import (
    SAMPLE_INPUT,
    SCHEMAS,
    conversion_answers,
    details_answer,
    lesson_answer,
    outline_answer,
    overview_answer,
)

SIZE = CourseSize(2, 3)


ALL_LABELS = [
    "planning the course outline",
    "creating course details",
    "writing the overview for module 1",
    "writing module 1, lesson 1",
    "writing module 1, lesson 2",
    "writing module 1, lesson 3",
    "writing the overview for module 2",
    "writing module 2, lesson 1",
    "writing module 2, lesson 2",
    "writing module 2, lesson 3",
]


def labels(provider):
    return [label for _, _, label in provider.calls]


@pytest.fixture(autouse=True)
def no_network(monkeypatch):
    def refuse(*args, **kwargs):
        raise AssertionError("tests must not use the network")

    monkeypatch.setattr(socket.socket, "connect", refuse)


@pytest.fixture(autouse=True)
def no_waiting(monkeypatch):
    monkeypatch.setattr("converter.retry.time.sleep", lambda seconds: None)


@pytest.fixture
def options(tmp_path):
    return ConversionOptions(size=SIZE, output_root=tmp_path / "output")


@pytest.fixture
def document(tmp_path):
    """A private copy of the sample document, so tests can change it."""
    path = tmp_path / "python-basics.txt"
    shutil.copy(SAMPLE_INPUT, path)
    return path


# ---------------------------------------------------------------------------
# A full conversion
# ---------------------------------------------------------------------------


def test_two_by_three_conversion_gives_a_valid_course(document, options):
    provider = FakeProvider(conversion_answers())
    events = []

    course_file = convert(document, provider, options, events.append)

    course = load_json(course_file)
    assert collect_errors(SCHEMAS.course_validator, course) == []
    assert labels(provider) == ALL_LABELS

    info = course["course"]
    assert info["courseTitle"] == "Python Basics for Complete Beginners"
    assert info["courseId"] == "python-basics-for-complete-beginners-beginner-v1"
    assert info["level"] == "Beginner"
    assert [len(module["lessons"]) for module in info["modules"]] == [3, 3]
    assert info["modules"][1]["lessons"][2]["lessonId"] == (
        "python-basics-for-complete-beginners-beginner-v1-mod-2-lesson-3"
    )
    assert [event.done for event in events] == list(range(1, 11))
    assert {event.total for event in events} == {10}


def test_each_lesson_prompt_holds_only_its_cited_sections(document, options):
    provider = FakeProvider(conversion_answers())

    convert(document, provider, options)

    prompts = {label: prompt for prompt, _, label in provider.calls}
    if_lesson = prompts["writing module 2, lesson 1"]
    assert "[s5] Python Basics for Complete Beginners > Making Decisions with if" in if_lesson
    assert "[s6]" not in if_lesson and "[s4]" not in if_lesson
    overview_2 = prompts["writing the overview for module 2"]
    assert all(f"[s{n}]" in overview_2 for n in (5, 6, 7))
    assert "[s4]" not in overview_2


def test_total_duration_is_the_sum_of_the_modules(document, options):
    course_file = convert(document, FakeProvider(conversion_answers()), options)

    modules = load_json(course_file)["course"]["modules"]
    module_minutes = []
    for module in modules:
        lessons = sum(lesson_minutes(lesson["duration"]) for lesson in module["lessons"])
        assert module["duration"] == format_minutes(lessons)
        module_minutes.append(lessons)

    total = load_json(course_file)["course"]["totalDuration"]
    assert total == format_minutes(sum(module_minutes))


def test_automatic_size_from_the_document(document, tmp_path):
    outline = outline_answer()
    outline["modules"] = [
        {
            "title": "Basics",
            "lessons": [
                {"title": "Variables and numbers", "sections": ["s1", "s2", "s3"]},
                {"title": "Text, decisions and loops", "sections": ["s4", "s5", "s6", "s7"]},
            ],
        }
    ]
    answers = [outline, details_answer(), overview_answer(0), lesson_answer(0), lesson_answer(1)]

    course_file = convert(document, FakeProvider(answers), ConversionOptions(output_root=tmp_path))

    assert [len(m["lessons"]) for m in load_json(course_file)["course"]["modules"]] == [2]


# ---------------------------------------------------------------------------
# Resuming and starting fresh
# ---------------------------------------------------------------------------


def test_resume_after_crash_continues_at_the_next_lesson(document, options):
    answers = conversion_answers()
    first = FakeProvider(answers[:5])  # outline, details, overview 1, lessons 1.1 and 1.2

    with pytest.raises(AssertionError, match="no answer left for: writing module 1, lesson 3"):
        convert(document, first, options)

    second = FakeProvider(answers[5:])
    events = []
    convert(document, second, options, events.append)

    assert labels(second) == ALL_LABELS[5:]  # starts at lesson 1.3; nothing repeated
    assert [event.reused for event in events] == [True] * 5 + [False] * 5


def test_changed_document_starts_a_fresh_run(document, options):
    convert(document, FakeProvider(conversion_answers()), options)
    document.write_text(document.read_text(encoding="utf-8") + "\nOne more line.\n", "utf-8")

    second = FakeProvider(conversion_answers())
    convert(document, second, options)

    assert labels(second) == ALL_LABELS  # everything written again, from the outline
    assert len(list(options.output_root.iterdir())) == 2  # one folder per version of the file


def test_same_document_with_another_size_is_refused(document, options):
    convert(document, FakeProvider(conversion_answers()), options)
    other_size = ConversionOptions(size=CourseSize(1, 2), output_root=options.output_root)

    with pytest.raises(CheckpointError, match="different course size"):
        convert(document, FakeProvider([]), other_size)


def test_saved_outline_for_another_document_is_refused(document, options):
    convert(document, FakeProvider(conversion_answers()), options)
    folder = next(options.output_root.iterdir())
    other = document.with_name("other.txt")
    other.write_text("Different text " * 50, encoding="utf-8")
    folder.rename(job_folder(other, file_sha256(other), options.output_root))

    with pytest.raises(CheckpointError, match="different document"):
        convert(other, FakeProvider([]), options)


def test_unreadable_document_stops_before_any_call(tmp_path, options):
    empty = tmp_path / "empty.txt"
    empty.write_bytes(b"")
    provider = FakeProvider([])

    with pytest.raises(ExtractionError, match="is empty"):
        convert(empty, provider, options)

    assert provider.calls == []


def test_title_without_latin_letters_still_gets_a_folder_and_id(document, options):
    answers = conversion_answers()
    answers[0]["courseTitle"] = "पायथन की मूल बातें"

    course_file = convert(document, FakeProvider(answers), options)

    # Falls back to the file name, python-basics.txt.
    assert load_json(course_file)["course"]["courseId"] == "python-basics-beginner-v1"


# ---------------------------------------------------------------------------
# Durations
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("text", "minutes"),
    [
        ("25 minutes", 25),
        ("45 min", 45),
        ("1.5 hours", 90),
        ("2 hrs", 120),
        ("About 30 Minutes", 30),
        ("half an hour", None),
        (None, None),
    ],
)
def test_lesson_minutes(text, minutes):
    assert lesson_minutes(text) == minutes


@pytest.mark.parametrize(
    ("minutes", "text"),
    [
        (0, "0 minutes"),
        (1, "1 minute"),
        (25, "25 minutes"),
        (60, "1 hour"),
        (75, "1 hour 15 minutes"),
        (240, "4 hours"),
    ],
)
def test_format_minutes(minutes, text):
    assert format_minutes(minutes) == text


def test_unreadable_lesson_duration_counts_as_planned_length(caplog):
    course = {
        "course": {
            "totalDuration": "",
            "modules": [
                {"duration": "", "lessons": [{"duration": "25 minutes"}, {"duration": "a while"}]},
                {"duration": "", "lessons": [{"duration": "12.5 minutes"}]},
            ],
        }
    }

    set_durations(course, SCHEMAS)

    modules = course["course"]["modules"]
    assert [module["duration"] for module in modules] == ["55 minutes", "13 minutes"]
    assert course["course"]["totalDuration"] == "1 hour 8 minutes"
    assert "could not be read; counting 30 minutes" in caplog.text
