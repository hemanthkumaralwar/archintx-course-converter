"""
convert.py

WHAT: The document converter: turns one .txt, .docx or .pdf file into a course
      JSON file in the format of samples/javascript-beginner.json.
      1. Read the document and split it into sections.
      2. Outline: course title, level, modules and lessons citing sections.
      3. Course details, then each module overview and lesson, written from
         the sections they cite and saved one piece at a time.
      4. Durations: each module is the sum of its lessons; the course is the
         sum of its modules.
      5. Final check against course_schema.json.

WHY:  Work is saved in a folder named after the file and its SHA-256 hash, so
      a stopped run resumes where it stopped, and an edited file always
      starts a fresh course instead of mixing old and new text.
"""

import hashlib
import logging
import math
import re
from dataclasses import dataclass
from pathlib import Path

from .checkpoint import load_outline, save_outline
from .chunking import split_sections
from .config import (
    ARRAY_PATH,
    LESSON_ARRAY_PATH,
    LESSON_ITEM_COUNTS,
    OUTPUT_ROOT,
    PLANNING_LESSON_MINUTES,
    SCHEMA_FILE,
    validate_config,
)
from .exceptions import ConfigurationError
from .extractors import extract_blocks
from .json_utils import get_value, load_json, save_json
from .pipeline import (
    ProgressCounter,
    ensure_output_dirs,
    finish,
    load_or_create_output,
    set_course_field,
    write_course,
)
from .planner import auto_course_size, check_course_size, generate_outline
from .schema_utils import build_schema_set
from .user_input import CourseRequest, slugify

logger = logging.getLogger(__name__)

OUTLINE_FILE = "outline.json"
COURSE_FOLDER = "course"

# Characters of the file's SHA-256 used in its folder name: enough to tell
# any two documents apart, short enough to read.
HASH_CHARS_IN_FOLDER = 12

# A duration written by the model, such as "25 minutes", "1.5 hours" or "45 min".
DURATION = re.compile(r"(\d+(?:\.\d+)?)\s*(hours?|hrs?|minutes?|mins?)\b", re.IGNORECASE)


@dataclass(frozen=True)
class ConversionOptions:
    """
    size:        modules and lessons per module, or None to choose from the document's length.
    output_root: folder that holds one subfolder per converted document.
    """

    size: object = None
    output_root: Path = OUTPUT_ROOT


def convert(path, provider, options=None, progress_callback=None, extract=extract_blocks):
    """
    WHAT: Convert one document into a course JSON file and return its path.

    PARAMETERS:
        path:              the .txt, .docx or .pdf file.
        provider:          an LLM provider (see providers.base.LLMProvider).
        options:           ConversionOptions; defaults to automatic size.
        progress_callback: optional function called with a pipeline.Progress
                           after every finished or reused piece.
        extract:           reads the file into blocks; the web app passes a
                           version that runs in a separate process with a time limit.

    RAISES:
        ExtractionError, ConfigurationError, CheckpointError, GenerationError,
        ValidationFailedError (all CourseGenerationError) for expected failures.
    """
    options = options or ConversionOptions()
    validate_config()
    path = Path(path)
    sections = split_sections(extract(path))
    size = options.size or auto_course_size(sections)
    check_course_size(size)

    digest = file_sha256(path)
    job_dir = job_folder(path, digest, options.output_root)
    schemas = build_schema_set(
        load_json(SCHEMA_FILE), ARRAY_PATH, LESSON_ARRAY_PATH, LESSON_ITEM_COUNTS
    )
    total = 2 + size.modules * (1 + size.lessons_per_module)  # outline, details, overviews, lessons
    progress = ProgressCounter(total, progress_callback or (lambda event: None))
    logger.info(
        "Converting %s: %d sections, %d modules x %d lessons",
        path.name,
        len(sections),
        size.modules,
        size.lessons_per_module,
    )

    outline = load_or_create_outline(job_dir, provider, sections, size, digest, progress)
    request = course_request(outline, size, job_dir, path)
    ensure_output_dirs(request)
    output = load_or_create_output(request, schemas, provider, progress)

    plan_modules = [
        {"title": module["title"], "lessons": [lesson["title"] for lesson in module["lessons"]]}
        for module in outline["modules"]
    ]
    write_course(
        request,
        schemas,
        provider,
        plan_modules,
        output,
        progress,
        lesson_sources(outline, sections),
    )

    set_durations(output, schemas)
    save_json(request.output_file, output)
    finish(request, schemas, plan_modules)
    return request.output_file


def file_sha256(path):
    """Return the SHA-256 of the file's bytes, as hex."""
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def job_folder(path, digest, output_root):
    """The folder for one document: '<file name>-<start of its SHA-256>'."""
    stem = safe_slug(Path(path).stem, fallback="document")
    return Path(output_root) / f"{stem}-{digest[:HASH_CHARS_IN_FOLDER]}"


def safe_slug(text, fallback):
    """
    WHAT: slugify(text), or the fallback when the text has no Latin letters or digits.

    WHY:  A course title or file name in another script (for example Hindi)
          has no characters slugify keeps; it must not stop the conversion.
    """
    try:
        return slugify(text)
    except ConfigurationError:
        return fallback


def load_or_create_outline(job_dir, provider, sections, size, digest, progress):
    """Return the saved outline for this document and size, or create and save one."""
    outline_file = job_dir / OUTLINE_FILE

    if outline_file.exists():
        outline = load_outline(outline_file, digest, size)
        progress.report("Course outline", reused=True)
        return outline

    outline = generate_outline(provider, sections, size)
    save_outline(outline_file, digest, size, outline)
    progress.report("Course outline")
    return outline


def course_request(outline, size, job_dir, path):
    """
    WHAT: The CourseRequest the shared pipeline needs, built from the outline.

    WHY:  Planned hours are lessons x planned lesson minutes, which makes the
          request's module count equal the outline's. The course ID follows the
          sample's "<title>-<level>-v1" pattern.
    """
    title_slug = safe_slug(outline["courseTitle"], fallback=safe_slug(path.stem, "course"))
    return CourseRequest(
        title=outline["courseTitle"],
        difficulty=outline["level"],
        duration_hours=size.modules * size.lessons_per_module * PLANNING_LESSON_MINUTES / 60,
        course_id_override=f"{title_slug.replace('_', '-')}-{outline['level']}-v1",
        lessons_per_module=size.lessons_per_module,
        output_root=job_dir,
        folder_name=COURSE_FOLDER,
    )


def lesson_sources(outline, sections):
    """For each module, for each lesson, the Sections that lesson cites."""
    by_id = {section.id: section for section in sections}
    return [
        [[by_id[section_id] for section_id in lesson["sections"]] for lesson in module["lessons"]]
        for module in outline["modules"]
    ]


# ---------------------------------------------------------------------------
# Durations
# ---------------------------------------------------------------------------


def lesson_minutes(text):
    """
    WHAT: Minutes in a duration such as "25 minutes" or "1.5 hours", or None.

    WHY:  Lesson durations are written by the model, so they are read
          defensively; anything unreadable is handled by the caller.
    """
    match = DURATION.search(text) if isinstance(text, str) else None

    if match is None:
        return None

    value = float(match.group(1))
    return value * 60 if match.group(2).lower().startswith("h") else value


def format_minutes(minutes):
    """
    WHAT: Write whole minutes the way the sample does: "25 minutes", "4 hours",
          or "1 hour 15 minutes".

    WHY:  Exact, never rounded to hours, so the course total always equals
          the sum of its modules.
    """
    hours, rest = divmod(int(minutes), 60)
    parts = []

    if hours:
        parts.append(f"{hours} hour" + ("s" if hours != 1 else ""))

    if rest or not hours:
        parts.append(f"{rest} minute" + ("s" if rest != 1 else ""))

    return " ".join(parts)


def set_durations(output, schemas):
    """
    WHAT: Set each module's duration to the sum of its lessons, and the
          course's totalDuration to the sum of its modules.

    WHY:  The model's own module and course durations need not add up (the
          team's sample says 12 hours for modules that add up to 37). A lesson
          duration that cannot be read counts as the planned lesson length.
    """
    total = 0

    for module in get_value(output, schemas.array_path):
        minutes = 0

        for lesson in module.get(schemas.lesson_path, []):
            value = lesson_minutes(lesson.get("duration"))

            if value is None:
                logger.warning(
                    "A lesson duration could not be read; counting %d minutes",
                    PLANNING_LESSON_MINUTES,
                )
                value = PLANNING_LESSON_MINUTES

            minutes += value

        # Rounded once (half up), so modules and total use the same whole minutes.
        whole_minutes = math.floor(minutes + 0.5)
        module["duration"] = format_minutes(whole_minutes)
        total += whole_minutes

    set_course_field(output, schemas, "totalDuration", format_minutes(total))
