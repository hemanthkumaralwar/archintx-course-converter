"""
The team's reference course (samples/javascript-beginner.json), loaded once for tests,
and fake LLM answers built from it for a 2-module x 2-lesson course.
"""

import copy

from converter import config
from converter.json_utils import load_json
from converter.lesson_checks import lesson_structure_errors
from converter.schema_utils import build_schema_set
from converter.validation import collect_errors

SAMPLE_FILE = config.PROJECT_ROOT / "samples" / "javascript-beginner.json"
SAMPLE = load_json(SAMPLE_FILE)["course"]
SAMPLE_LESSONS = [lesson for module in SAMPLE["modules"] for lesson in module["lessons"]]

SCHEMAS = build_schema_set(
    load_json(config.SCHEMA_FILE),
    config.ARRAY_PATH,
    config.LESSON_ARRAY_PATH,
    config.LESSON_ITEM_COUNTS,
)


def valid_sample_lessons():
    """Sample lessons that pass both the lesson schema and every content check."""
    return [
        lesson
        for module in SAMPLE["modules"]
        for lesson in module["lessons"]
        if not collect_errors(SCHEMAS.lesson_validator, lesson)
        and not lesson_structure_errors(lesson)
    ]


LESSONS = valid_sample_lessons()


def plan_answer():
    return {
        "modules": [
            {"title": f"Module {m}", "lessons": [f"Lesson {m}.{n}" for n in (1, 2)]} for m in (1, 2)
        ]
    }


def details_answer():
    course = copy.deepcopy(SAMPLE)
    course["modules"] = []
    return {"course": course}


def overview_answer(index):
    overview = copy.deepcopy(SAMPLE["modules"][index])
    overview["lessons"] = []
    return overview


def lesson_answer(index):
    return copy.deepcopy(LESSONS[index])


# Converter: answers for samples/inputs/python-basics.txt

SAMPLE_INPUT = config.PROJECT_ROOT / "samples" / "inputs" / "python-basics.txt"


def outline_answer():
    return {
        "courseTitle": "Python Basics for Complete Beginners",
        "level": "beginner",
        "modules": [
            {
                "title": "Core Data and Variables",
                "lessons": [
                    {"title": "Introduction to Python Variables", "sections": ["s1", "s2"]},
                    {"title": "Numbers and Arithmetic", "sections": ["s3"]},
                    {"title": "Working with Text", "sections": ["s4"]},
                ],
            },
            {
                "title": "Control Flow",
                "lessons": [
                    {"title": "Making Decisions with if", "sections": ["s5"]},
                    {"title": "Repeating Work with Loops", "sections": ["s6"]},
                    {"title": "Putting It Together", "sections": ["s7"]},
                ],
            },
        ],
    }


def conversion_answers():
    """Answers in the order the converter asks for them, for 2 modules x 3 lessons
    of samples/inputs/python-basics.txt."""
    return [
        outline_answer(),
        details_answer(),
        overview_answer(0),
        lesson_answer(0),
        lesson_answer(1),
        lesson_answer(2),
        overview_answer(1),
        lesson_answer(3),
        lesson_answer(4),
        lesson_answer(5),
    ]
