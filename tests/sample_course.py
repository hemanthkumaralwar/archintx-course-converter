"""The team's reference course (samples/javascript-beginner.json), loaded once for tests."""

import json
from pathlib import Path

SAMPLE_FILE = Path(__file__).resolve().parent.parent / "samples" / "javascript-beginner.json"


def _load_sample_lessons():
    with SAMPLE_FILE.open(encoding="utf-8") as file:
        course = json.load(file)["course"]
    return [lesson for module in course["modules"] for lesson in module["lessons"]]


SAMPLE_LESSONS = _load_sample_lessons()
