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
