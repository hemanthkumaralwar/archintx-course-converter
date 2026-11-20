"""Shared test fixtures."""

import copy

import pytest

from tests.sample_course import SAMPLE_LESSONS

# A sample lesson that passes every content check; used as the base for broken copies.
VALID_LESSON_ID = "javascript-beginner-mod-1-lesson-1"


@pytest.fixture
def lesson():
    """A fresh copy of a valid sample lesson, safe to change inside a test."""
    by_id = {item["lessonId"]: item for item in SAMPLE_LESSONS}
    return copy.deepcopy(by_id[VALID_LESSON_ID])
