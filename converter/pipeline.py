"""
pipeline.py

WHAT: The full workflow for one course:
      1. Check settings, load course_schema.json, build the schema set.
      2. Plan: every module title and its lesson titles (or reuse the saved plan).
      3. Course details: the course-level fields (or reuse the saved output).
      4. For each module: write the overview, then write each lesson in order,
         saving after every piece.
      5. Final check: validate the finished file against course_schema.json.

WHY:  Each piece is saved as soon as it is valid. If the run stops, only the
      piece in progress is lost, and rerunning continues from the next lesson.
      Progress is reported through a callback, not printed, so the command
      line and the web page can each show it their own way. Log messages
      never include course text (titles, lessons), only counts and steps.
"""

import logging
from copy import deepcopy
from dataclasses import dataclass

from .checkpoint import load_plan, save_plan
from .config import (
    ARRAY_PATH,
    LESSON_ARRAY_PATH,
    LESSON_ITEM_COUNTS,
    SCHEMA_FILE,
    validate_config,
)
from .exceptions import CheckpointError, ConfigurationError, DataPathError
from .json_utils import get_value, load_json, replace_array, save_json
from .module_writer import write_lesson, write_overview
from .planner import generate_course_details, generate_plan
from .schema_utils import build_schema_set
from .validation import ensure_valid

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class Progress:
    """
    One finished piece of the course.

    done:   pieces finished so far, including pieces reused from an earlier run.
    total:  pieces in the whole course (plan, details, every overview and lesson).
    label:  what the piece is, such as "Lesson 1.2: Declaring variables".
    reused: True when the piece came from a saved earlier run.
    """

    done: int
    total: int
    label: str
    reused: bool = False


class ProgressCounter:
    """Counts finished pieces and passes each one to the caller's callback."""

    def __init__(self, total, callback):
        self.total = total
        self.done = 0
        self._callback = callback

    def report(self, label, reused=False):
        self.done += 1
        self._callback(Progress(self.done, self.total, label, reused))


def total_pieces(request):
    """Plan + course details + one overview per module + every lesson."""
    return 2 + request.module_count * (1 + request.lessons_per_module)


def _ignore_progress(_event):
    """Default callback: progress reporting is optional."""


@dataclass(frozen=True)
class CourseContext:
    """Everything that stays the same while the modules of one course are written."""

    request: object
    schemas: object
    provider: object
    plan_modules: list
    details: dict
    # Converter only: lesson_sources[module][lesson] is the list of document
    # Sections that lesson cites. None for the title-based generator.
    lesson_sources: list = None

    def lesson_source(self, m_index, l_index):
        return self.lesson_sources[m_index][l_index] if self.lesson_sources else None

    def module_source(self, m_index):
        """Every section the module's lessons cite, once each, in first-cited order."""
        if not self.lesson_sources:
            return None
        unique = {}
        for sections in self.lesson_sources[m_index]:
            for section in sections:
                unique.setdefault(section.id, section)
        return list(unique.values())


def ensure_output_dirs(request):
    """
    WHAT: Create the course's output and error folders.

    RAISES:
        ConfigurationError: if a folder cannot be created.
    """
    try:
        request.output_dir.mkdir(parents=True, exist_ok=True)
        request.error_dir.mkdir(parents=True, exist_ok=True)
    except OSError as exc:
        raise ConfigurationError(
            f"Could not create output folders under '{request.output_dir}': {exc}"
        ) from exc


def load_or_create_plan(request, provider, progress):
    """
    WHAT: Return the planned modules, from the saved plan if it exists,
          otherwise by generating and saving a new plan.

    RETURNS:
        A list of {"title", "lessons"} dicts.
    """
    if request.plan_file.exists():
        modules = load_plan(request.plan_file, request)
        progress.report("Course plan", reused=True)
        return modules

    modules = generate_plan(provider, request)
    save_plan(request.plan_file, request, modules)
    progress.report("Course plan")
    return modules


def load_or_create_output(request, schemas, provider, progress):
    """
    WHAT: Return the course object, from the saved output if it exists,
          otherwise by generating the course details and saving them.

    RETURNS:
        A dict holding the course, with its module list possibly partly filled.
    """
    if request.output_file.exists():
        output = load_json(request.output_file)

        if not isinstance(output, dict):
            raise CheckpointError(
                f"The output file {request.output_file} must contain a JSON object."
            )

        progress.report("Course details", reused=True)
        return output

    details = generate_course_details(provider, request, schemas)

    # IDs are set by code so they follow the same pattern every time.
    # courseId is placed where the schema defines it (for example inside "course").
    course_values = {
        "courseId": request.course_id,
        "courseTitle": request.title,
        "level": request.level_display,
        "totalDuration": request.total_duration_text,
    }

    for name, value in course_values.items():
        set_course_field(details, schemas, name, value)

    save_json(request.output_file, details)
    progress.report("Course details")
    return details


def set_course_field(course, schemas, name, value):
    """
    WHAT: Set a course-level field where the schema puts it, for example
          totalDuration at "course.totalDuration". Does nothing if the schema
          has no such field.
    """
    path = (schemas.course_field_paths or {}).get(name)

    if path:
        parts = path.split(".")
        parent = get_value(course, ".".join(parts[:-1])) if len(parts) > 1 else course
        parent[parts[-1]] = value


def course_details_from(output, array_path):
    """
    WHAT: Return a copy of the course object with its module list emptied.

    WHY:  Prompts need the course details as context, but not the modules
          already written. Sending them would waste tokens.
    """
    details = deepcopy(output)
    replace_array(details, array_path, [])
    return details


def write_course(request, schemas, provider, plan_modules, output, progress, lesson_sources=None):
    """
    WHAT: Write every missing module overview and lesson, in order.

    WHY:  Working in this order means a run can stop at any point and resume
          from the exact lesson that was not finished.

    RAISES:
        DataPathError:   if the module list or a module's lessons are malformed.
        CheckpointError: if the saved output has more modules than the plan.
    """
    modules = get_value(output, schemas.array_path)

    if not isinstance(modules, list):
        raise DataPathError(f"'{schemas.array_path}' in the output must be an array.")

    if len(modules) > len(plan_modules):
        raise CheckpointError(
            f"The output has {len(modules)} modules but the plan has {len(plan_modules)}. "
            f"Delete '{request.output_dir}' to start over."
        )

    context = CourseContext(
        request,
        schemas,
        provider,
        plan_modules,
        course_details_from(output, schemas.array_path),
        lesson_sources,
    )

    for m_index in range(len(plan_modules)):
        _write_module(context, m_index, modules, output, progress)


def _write_module(context, m_index, modules, output, progress):
    """
    WHAT: Write module m_index: its overview if missing, then each missing lesson.

    WHY:  Each piece is saved to the output file as soon as it is valid.
    """
    request, schemas = context.request, context.schemas
    plan_module = context.plan_modules[m_index]
    number = m_index + 1
    overview_label = f"Module {number} overview: {plan_module['title']}"

    if m_index < len(modules):
        progress.report(overview_label, reused=True)
    else:
        overview = write_overview(
            context.provider,
            request,
            m_index,
            context.plan_modules,
            context.details,
            schemas,
            source_sections=context.module_source(m_index),
        )
        overview["moduleId"] = f"{request.course_id}-mod-{number}"
        overview[schemas.lesson_path] = []  # Lessons are added one at a time below.
        modules.append(overview)
        save_json(request.output_file, output)
        progress.report(overview_label)

    module = modules[m_index]
    lessons = module.get(schemas.lesson_path)

    if not isinstance(lessons, list):
        raise DataPathError(f"Module {number} in the output has no '{schemas.lesson_path}' list.")

    for l_index, lesson_title in enumerate(plan_module["lessons"]):
        label = f"Lesson {number}.{l_index + 1}: {lesson_title}"

        if l_index < len(lessons):
            progress.report(label, reused=True)
            continue

        lesson = write_lesson(
            context.provider,
            request,
            m_index,
            l_index,
            context.plan_modules,
            course_overview_for_prompt(module, schemas.lesson_path),
            context.details,
            schemas,
            source_sections=context.lesson_source(m_index, l_index),
        )
        lesson["lessonId"] = f"{request.course_id}-mod-{number}-lesson-{l_index + 1}"
        lessons.append(lesson)
        save_json(request.output_file, output)
        progress.report(label)


def course_overview_for_prompt(module, lesson_path):
    """
    WHAT: Return the module overview without its lesson list.

    WHY:  The lessons are already in the output file. Sending them again in
          every lesson prompt would add a lot of tokens for no benefit.
    """
    overview = deepcopy(module)
    overview[lesson_path] = []
    return overview


def finish(request, schemas, plan_modules):
    """
    WHAT: Read the saved file back and check it fully.

    WHY:  Reading from disk checks exactly what the user receives. Each lesson
          was checked as it was written. This final pass checks the whole course
          against course_schema.json and confirms every module has all its lessons.

    RAISES:
        DataPathError:         if a module has the wrong number of lessons.
        ValidationFailedError: if the course breaks the schema.
    """
    final = load_json(request.output_file)
    modules = get_value(final, schemas.array_path)

    if len(modules) != len(plan_modules):
        raise DataPathError(
            f"The final course has {len(modules)} modules; expected {len(plan_modules)}."
        )

    for number, module in enumerate(modules, start=1):
        lessons = module.get(schemas.lesson_path, [])

        if len(lessons) != request.lessons_per_module:
            raise DataPathError(
                f"Module {number} has {len(lessons)} lessons; "
                f"expected {request.lessons_per_module}."
            )

    ensure_valid(schemas.course_validator, final, "Final course")
    logger.info("Course complete and valid: %d modules", len(modules))


def run_pipeline(request, provider, progress_callback=None):
    """
    WHAT: Run every step for one course request.

    WHY:  This is the only function generate.py calls, so the whole workflow
          is visible in one place. The LLM provider is passed in, so tests can
          use a fake one and the entry point decides between Gemini and OpenAI.

    PARAMETERS:
        progress_callback: optional function called with a Progress after
                           every finished (or reused) piece.

    RETURNS:
        The path of the finished course JSON file.

    RAISES:
        CourseGenerationError subclasses for any expected failure.
    """
    validate_config()
    ensure_output_dirs(request)

    schemas = build_schema_set(
        load_json(SCHEMA_FILE),
        ARRAY_PATH,
        LESSON_ARRAY_PATH,
        LESSON_ITEM_COUNTS,
    )
    logger.info(
        "Schema arrays: modules at '%s', lessons at '%s'", schemas.array_path, schemas.lesson_path
    )
    logger.info(
        "Planning %d modules x %d lessons for %g hours",
        request.module_count,
        request.lessons_per_module,
        request.duration_hours,
    )

    # An output without its plan cannot be resumed safely.
    if request.output_file.exists() and not request.plan_file.exists():
        raise CheckpointError(
            f"An output file exists without its plan. Delete '{request.output_dir}' to start over."
        )

    progress = ProgressCounter(total_pieces(request), progress_callback or _ignore_progress)
    plan_modules = load_or_create_plan(request, provider, progress)
    output = load_or_create_output(request, schemas, provider, progress)

    write_course(request, schemas, provider, plan_modules, output, progress)
    finish(request, schemas, plan_modules)
    return request.output_file
