"""
module_writer.py

WHAT: Writes the two kinds of pieces the pipeline saves:
      - write_overview: one module's overview (lesson list empty),
      - write_lesson:   one lesson.
      Each is checked against its own schema and the rules in
      lesson_checks.py, and retried with feedback.
      Rejected output is saved to the course's errors folder.

WHY:  Small requests are less likely to be rejected or cut off, and a
      failed lesson can be retried without redoing the rest of the course.
"""

import json

from .exceptions import ValidationFailedError
from .json_utils import save_json
from .lesson_checks import lesson_structure_errors, repair_lesson, section_for_error
from .prompts import build_lesson_prompt, build_overview_prompt
from .retry import run_with_retries
from .validation import ensure_valid


def _save_rejected(path, index_label, attempt_number, errors, generated, error_dir):
    """
    WHAT: Save a rejected response so you can see what the model produced.

    WHY:  File names include the attempt number, so earlier attempts are not
          overwritten.
    """
    save_json(
        error_dir / f"{path}_attempt_{attempt_number}.json",
        {
            "item": index_label,
            "attempt": attempt_number,
            "errors": errors,
            "generated": generated,
        },
    )


# How many times one failing section is sent back to the model for a fix.
SECTION_REPAIR_ROUNDS = 2


def repair_and_check(lesson):
    """
    WHAT: Fix formatting slips in a generated lesson, then return its structure errors.

    WHY:  Repairs run again after every section fix from the model, because a
          returned section can repeat a slip the repairs handle (for example,
          code lines in step order).
    """
    repair_lesson(lesson)
    return lesson_structure_errors(lesson)


def repair_section(provider, request, lesson, key, errors, schemas):
    """
    WHAT: Ask the model to fix only one field of a lesson, given the errors for it.

    WHY:  Regenerating a whole lesson repeats the same mistake. A smaller request
          with the current field and its exact problems is much more likely to
          produce a fix. The rest of the lesson is left as it is.

    RETURNS:
        The fixed field value, or None if the schema has no such field.
    """
    section_schema = schemas.lesson_request.get("properties", {}).get(key)

    if section_schema is None:
        return None

    current = json.dumps(lesson.get(key), ensure_ascii=False, indent=2)
    problems = "\n".join(f"- {error}" for error in errors)

    prompt = f"""
Fix only the "{key}" field of one lesson in the course "{request.title}".

Current "{key}" value:
{current}

Problems to fix:
{problems}

Rules:
- Change only what is needed to fix these problems. Keep the meaning and the teaching content.
- Keep every limit named in the problems, such as a maximum number of lines.
- Keep the same JSON shape as the current value.
- Return only the JSON for "{key}", with no Markdown fences or extra text.
"""

    return provider.generate_json(
        prompt=prompt, schema=section_schema, label=f"repairing the {key} field"
    )


def write_overview(provider, request, index, plan_modules, details, schemas):
    """
    WHAT: Generate and validate the overview of module index (zero-based).

    RETURNS:
        A module dict with an empty lesson list.

    RAISES:
        GenerationError: if no valid overview is produced after retries.
    """
    label = f"Module {index + 1} overview"

    def attempt(previous_errors, attempt_number):
        data = provider.generate_json(
            prompt=build_overview_prompt(request, index, plan_modules, details, previous_errors),
            schema=schemas.overview_request,
            label=f"writing the overview for module {index + 1}",
        )

        if not isinstance(data, dict):
            raise ValidationFailedError(
                f"{label} must be a JSON object.",
                errors=[f"{label}: top-level value is not an object"],
            )

        try:
            ensure_valid(schemas.overview_validator, data, label)
        except ValidationFailedError as exc:
            _save_rejected(
                f"module_{index + 1}_overview",
                index + 1,
                attempt_number,
                exc.errors,
                data,
                request.error_dir,
            )
            raise

        return data

    return run_with_retries(label, attempt)


def write_lesson(
    provider, request, module_index, lesson_index, plan_modules, module_overview, details, schemas
):
    """
    WHAT: Generate and validate one lesson, identified by module and lesson position.

    PARAMETERS:
        module_index:    zero-based module position.
        lesson_index:    zero-based lesson position inside the module.
        plan_modules:    the full plan, used for context.
        module_overview: the already-written overview of this module.
        details:         the course-level fields.

    RETURNS:
        A lesson dict that passes the exact-count lesson validator.

    RAISES:
        GenerationError: if no valid lesson is produced after retries.
    """
    label = f"Module {module_index + 1}, lesson {lesson_index + 1}"

    def attempt(previous_errors, attempt_number):
        data = provider.generate_json(
            prompt=build_lesson_prompt(
                request,
                module_index,
                lesson_index,
                plan_modules,
                module_overview,
                details,
                previous_errors,
            ),
            schema=schemas.lesson_request,
            label=f"writing {label.lower()}",
        )

        if not isinstance(data, dict):
            raise ValidationFailedError(
                f"{label} must be a JSON object.",
                errors=[f"{label}: top-level value is not an object"],
            )

        structure_errors = repair_and_check(data)

        # If the errors all belong to one field, ask the model to fix only that field.
        for _ in range(SECTION_REPAIR_ROUNDS):
            if not structure_errors:
                break

            keys = {section_for_error(error) for error in structure_errors}

            if len(keys) != 1 or None in keys:
                break

            key = keys.pop()
            fixed = repair_section(provider, request, data, key, structure_errors, schemas)

            if fixed is None:
                break

            data[key] = fixed
            structure_errors = repair_and_check(data)

        if structure_errors:
            _save_rejected(
                f"module_{module_index + 1}_lesson_{lesson_index + 1}",
                f"{module_index + 1}.{lesson_index + 1}",
                attempt_number,
                structure_errors,
                data,
                request.error_dir,
            )
            shown = structure_errors[:8]
            raise ValidationFailedError(
                f"{label} has invalid lesson structure:\n  " + "\n  ".join(shown),
                errors=structure_errors,
            )

        try:
            ensure_valid(schemas.lesson_validator, data, label)
        except ValidationFailedError as exc:
            _save_rejected(
                f"module_{module_index + 1}_lesson_{lesson_index + 1}",
                f"{module_index + 1}.{lesson_index + 1}",
                attempt_number,
                exc.errors,
                data,
                request.error_dir,
            )
            raise

        return data

    return run_with_retries(label, attempt)
