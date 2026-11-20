"""
planner.py

WHAT: The planning steps that run before any module is written:
      - generate_outline:        (converter) course title, level, modules and
                                 lessons from a document, each lesson citing
                                 the sections it is based on.
      - generate_plan:           (title-based generator) every module title
                                 and its lesson titles.
      - generate_course_details: the course-level fields with an empty module list.

WHY:  Planning first gives every later step the same map of the course.
      Lesson titles are fixed here, so each lesson can be written separately
      and in order, and resumed without changing the outline.
"""

import logging
import math
from dataclasses import dataclass

from .config import MAX_MODULES
from .exceptions import ConfigurationError, ValidationFailedError
from .json_utils import replace_array
from .prompts import (
    LEVELS,
    build_details_prompt,
    build_outline_prompt,
    build_plan_prompt,
    outline_schema,
    plan_schema,
)
from .retry import run_with_retries
from .validation import ensure_valid

logger = logging.getLogger(__name__)

# Document characters per lesson when the size is chosen automatically: one
# section (chunking.DEFAULT_MAX_SECTION_CHARS), about one printed page.
CHARS_PER_LESSON = 3000

# Automatic sizes stay between these. 64 lessons is the team's sample size
# (8 x 8), about 74 API calls: roughly one day of free-tier quota.
MIN_AUTO_LESSONS = 2
MAX_AUTO_LESSONS = 64

# The team's sample has 8 lessons per module; no module is larger.
MAX_LESSONS_PER_MODULE = 8


@dataclass(frozen=True)
class CourseSize:
    """Number of modules and lessons per module for one course."""

    modules: int
    lessons_per_module: int


def auto_course_size(sections):
    """
    WHAT: Choose a course size from the document's length.

    HOW:  One lesson per CHARS_PER_LESSON characters, kept between
          MIN_AUTO_LESSONS and MAX_AUTO_LESSONS, in as few modules as the
          8-lesson limit allows, with lessons spread evenly across modules.

    EXAMPLE: 50,000 characters -> 17 lessons -> 3 modules of 6 lessons.
    """
    characters = sum(len(section.text) for section in sections)
    lessons = math.ceil(characters / CHARS_PER_LESSON)
    lessons = min(max(lessons, MIN_AUTO_LESSONS), MAX_AUTO_LESSONS)
    modules = math.ceil(lessons / MAX_LESSONS_PER_MODULE)
    return CourseSize(modules, math.ceil(lessons / modules))


def check_course_size(size):
    """
    WHAT: Reject a course size a user asked for if it is outside the limits.

    RAISES:
        ConfigurationError: if a count is not a whole number in range.
    """
    limits = (
        ("modules", size.modules, MAX_MODULES),
        ("lessons per module", size.lessons_per_module, MAX_LESSONS_PER_MODULE),
    )

    for name, value, maximum in limits:
        if not isinstance(value, int) or not 1 <= value <= maximum:
            raise ConfigurationError(
                f"The number of {name} must be from 1 to {maximum} (got {value})."
            )


# ---------------------------------------------------------------------------
# Outline from a document (the converter)
# ---------------------------------------------------------------------------


def generate_outline(provider, sections, size):
    """
    WHAT: Ask the model for a course outline of the given size, built from the
          document sections, and return it once it is valid.

    RETURNS:
        {"courseTitle": str, "level": str,
         "modules": [{"title": str, "lessons": [{"title": str, "sections": [ids]}]}]}

    RAISES:
        ValueError:         if there are no sections (extraction never returns none).
        ConfigurationError: if the size is out of range.
        GenerationError:    if no valid outline is produced after retries.
    """
    if not sections:
        raise ValueError("generate_outline needs at least one section.")

    check_course_size(size)
    section_ids = {section.id for section in sections}

    def attempt(previous_errors, attempt_number):
        data = provider.generate_json(
            prompt=build_outline_prompt(sections, size, previous_errors),
            schema=outline_schema(),
            label="planning the course outline",
        )
        return validate_outline(data, size, section_ids)

    outline = run_with_retries("Course outline", attempt)
    cited = {
        section_id
        for module in outline["modules"]
        for lesson in module["lessons"]
        for section_id in lesson["sections"]
    }
    logger.info(
        "Outline: %d modules x %d lessons; %d of %d sections cited",
        size.modules,
        size.lessons_per_module,
        len(cited),
        len(section_ids),
    )
    return outline


def validate_outline(data, size, section_ids):
    """
    WHAT: Check an outline's shape, counts and section ids, and return it cleaned.

    WHY:  The schema cannot fix counts or know which section ids exist. Every
          problem is collected, so the next attempt can fix them all at once.

    RAISES:
        ValidationFailedError: with every problem found.
    """
    if not isinstance(data, dict) or not isinstance(data.get("modules"), list):
        raise ValidationFailedError(
            "The outline must be an object with a 'modules' list.",
            errors=['top-level value must be {"courseTitle": ..., "level": ..., "modules": [...]}'],
        )

    errors = _outline_header_errors(data)
    modules = data["modules"]

    if len(modules) != size.modules:
        errors.append(f"expected {size.modules} modules, got {len(modules)}")

    cleaned = []

    for number, module in enumerate(modules, start=1):
        module_errors, module_cleaned = _outline_module(number, module, size, section_ids)
        errors += module_errors
        cleaned.append(module_cleaned)

    if errors:
        raise ValidationFailedError(
            "The course outline is invalid:\n  " + "\n  ".join(errors), errors=errors
        )

    return {"courseTitle": data["courseTitle"].strip(), "level": data["level"], "modules": cleaned}


def _outline_header_errors(data):
    errors = []
    title = data.get("courseTitle")

    if not isinstance(title, str) or not title.strip():
        errors.append("courseTitle is empty")

    if data.get("level") not in LEVELS:
        errors.append(f"level must be one of: {', '.join(LEVELS)}")

    return errors


def _outline_module(number, module, size, section_ids):
    """Return (errors, cleaned module) for one outline module."""
    if not isinstance(module, dict):
        return [f"module {number} is not an object"], None

    errors = _title_errors(module.get("title"), f"module {number}")
    lessons = module.get("lessons")

    if not isinstance(lessons, list) or len(lessons) != size.lessons_per_module:
        count = len(lessons) if isinstance(lessons, list) else "no list"
        errors.append(
            f"module {number} must have exactly {size.lessons_per_module} lessons (got {count})"
        )
        return errors, None

    cleaned = []

    for l_number, lesson in enumerate(lessons, start=1):
        lesson_errors, lesson_cleaned = _outline_lesson(
            f"module {number} lesson {l_number}", lesson, section_ids
        )
        errors += lesson_errors
        cleaned.append(lesson_cleaned)

    titles = [lesson["title"].lower() for lesson in cleaned if lesson]

    if len(set(titles)) != len(titles):
        errors.append(f"module {number} has duplicate lesson titles")

    return errors, {"title": str(module.get("title", "")).strip(), "lessons": cleaned}


def _outline_lesson(label, lesson, section_ids):
    """Return (errors, cleaned lesson) for one outline lesson."""
    if not isinstance(lesson, dict):
        return [f"{label} is not an object"], None

    errors = _title_errors(lesson.get("title"), label)
    cited = lesson.get("sections")

    if not isinstance(cited, list) or not cited:
        errors.append(f"{label} must cite at least one section")
        cited = []

    unknown = [str(section_id) for section_id in cited if section_id not in section_ids]

    if unknown:
        errors.append(f"{label} cites sections that do not exist: {', '.join(unknown)}")

    # Repeated ids are dropped, keeping the model's order.
    sections = list(dict.fromkeys(section_id for section_id in cited if section_id in section_ids))
    return errors, {"title": str(lesson.get("title", "")).strip(), "sections": sections}


def _title_errors(title, label):
    if not isinstance(title, str) or not title.strip():
        return [f"{label} has no title"]
    return []


# ---------------------------------------------------------------------------
# Plan from a title (the original generator)
# ---------------------------------------------------------------------------


def validate_plan(data, request):
    """
    WHAT: Check the plan's module and lesson counts and return cleaned titles.

    WHY:  The schema does not fix the counts (it would be too complex for
          Gemini), so they are checked here. Duplicate lesson titles inside a
          module are also rejected, because they would produce repeated lessons.

    RETURNS:
        A list of {"title": str, "lessons": [str, ...]} dicts.

    RAISES:
        ValidationFailedError: if the shape, counts, or titles are wrong.
    """
    if not isinstance(data, dict) or not isinstance(data.get("modules"), list):
        raise ValidationFailedError(
            "The plan must be an object with a 'modules' list.",
            errors=['top-level value must be {"modules": [...]}'],
        )

    modules = data["modules"]
    errors = []

    if len(modules) != request.module_count:
        errors.append(f"expected {request.module_count} modules, got {len(modules)}")

    for m_number, module in enumerate(modules, start=1):
        errors += _plan_module_errors(m_number, module, request.lessons_per_module)

    if errors:
        raise ValidationFailedError(
            "The course plan is invalid:\n  " + "\n  ".join(errors),
            errors=errors,
        )

    return [
        {
            "title": module["title"].strip(),
            "lessons": [lesson.strip() for lesson in module["lessons"]],
        }
        for module in modules
    ]


def _plan_module_errors(m_number, module, lessons_per_module):
    """Return the problems with one module of a title-based plan."""
    if not isinstance(module, dict):
        return [f"module {m_number} is not an object"]

    errors = _title_errors(module.get("title"), f"module {m_number}")
    lessons = module.get("lessons")

    if not isinstance(lessons, list) or len(lessons) != lessons_per_module:
        count = len(lessons) if isinstance(lessons, list) else "no list"
        errors.append(
            f"module {m_number} must have exactly {lessons_per_module} lesson titles (got {count})"
        )
        return errors

    cleaned = []
    for l_number, lesson in enumerate(lessons, start=1):
        if not isinstance(lesson, str) or not lesson.strip():
            errors.append(f"module {m_number} lesson {l_number} is empty")
        else:
            cleaned.append(lesson.strip())

    if len(set(cleaned)) != len(cleaned):
        errors.append(f"module {m_number} has duplicate lesson titles")

    return errors


def generate_plan(provider, request):
    """
    WHAT: Ask the model for every module and lesson title, and return them once valid.

    RETURNS:
        A list of module dicts, each with a title and its lesson titles.

    RAISES:
        GenerationError: if no valid plan is produced after retries.
    """

    def attempt(previous_errors, attempt_number):
        data = provider.generate_json(
            prompt=build_plan_prompt(request, previous_errors),
            schema=plan_schema(),
            label="planning the course",
        )
        return validate_plan(data, request)

    return run_with_retries("Course plan", attempt)


def generate_course_details(provider, request, schemas):
    """
    WHAT: Ask the model for the course-level fields. The module list is kept empty.

    RETURNS:
        A dict that matches the course schema, with its module list set to [].

    RAISES:
        GenerationError: if no valid course details are produced after retries.
    """

    def attempt(previous_errors, attempt_number):
        data = provider.generate_json(
            prompt=build_details_prompt(request, previous_errors),
            schema=schemas.details_request,
            label="creating course details",
        )

        if not isinstance(data, dict):
            raise ValidationFailedError(
                "Course details must be a JSON object.",
                errors=["top-level value is not an object"],
            )

        ensure_valid(schemas.details_validator, data, "Course details")
        return data

    details = run_with_retries("Course details", attempt)

    # The module list must be empty at this stage, whatever the model returned.
    replace_array(details, schemas.array_path, [])
    return details
