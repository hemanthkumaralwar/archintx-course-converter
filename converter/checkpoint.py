"""
checkpoint.py

WHAT: Saves and loads the plan of a course so a stopped run can resume:
      - save_plan / load_plan:       the title-based generator's plan.
      - save_outline / load_outline: the converter's outline, with the input
                                     file's SHA-256 and the course size.

WHY:  The plan costs an API call and fixes all titles. Saving it means a
      resumed run keeps the same outline, so lessons already written still
      fit the rest of the course.
"""

from .exceptions import CheckpointError
from .json_utils import load_json, save_json


def save_plan(path, request, modules):
    """
    WHAT: Write the request and the planned modules to the plan file.

    RAISES:
        JSONFileError: if the file cannot be written.
    """
    save_json(path, {"request": request.as_dict(), "modules": modules})


def load_plan(path, request):
    """
    WHAT: Read the plan file and check that it matches the current request.

    WHY:  A plan from a different title, difficulty, or duration must not be
          reused, or the course would mix two designs.

    RETURNS:
        The list of planned modules.

    RAISES:
        CheckpointError: if the file is incomplete, the request differs, or
                         the counts are wrong.
        JSONFileError:   if the file cannot be read.
    """
    data = load_json(path)

    if not isinstance(data, dict):
        raise CheckpointError("The plan file must contain a JSON object.")

    for key in ("request", "modules"):
        if key not in data:
            raise CheckpointError(f"The plan file is missing '{key}'.")

    if data["request"] != request.as_dict():
        raise CheckpointError(
            "The saved plan was made for a different title, difficulty, duration "
            "or number of lessons per module. "
            f"Delete the folder '{request.output_dir}' to start over."
        )

    modules = data["modules"]

    if not isinstance(modules, list) or len(modules) != request.module_count:
        raise CheckpointError(f"The saved plan must contain {request.module_count} modules.")

    for number, module in enumerate(modules, start=1):
        valid = (
            isinstance(module, dict)
            and isinstance(module.get("title"), str)
            and module["title"].strip()
            and isinstance(module.get("lessons"), list)
            and len(module["lessons"]) == request.lessons_per_module
            and all(isinstance(lesson, str) and lesson.strip() for lesson in module["lessons"])
        )

        if not valid:
            raise CheckpointError(
                f"Module {number} in the saved plan is incomplete. "
                f"It needs a title and {request.lessons_per_module} lesson titles."
            )

    return modules


def save_outline(path, source_sha256, size, outline):
    """
    WHAT: Write the converter's outline with the input file's hash and the course size.

    RAISES:
        JSONFileError: if the file cannot be written.
    """
    save_json(
        path,
        {
            "source_sha256": source_sha256,
            "size": {"modules": size.modules, "lessons_per_module": size.lessons_per_module},
            "outline": outline,
        },
    )


def load_outline(path, source_sha256, size):
    """
    WHAT: Read a saved outline and check it belongs to this file and course size.

    WHY:  The folder name already contains the file's hash, but a renamed or
          copied folder must not mix two documents. A different size would
          give a course that does not match its own outline.

    RETURNS:
        The saved outline.

    RAISES:
        CheckpointError: if the file is incomplete or was saved for another
                         document or another course size.
        JSONFileError:   if the file cannot be read.
    """
    data = load_json(path)

    if not isinstance(data, dict) or not isinstance(data.get("outline"), dict):
        raise CheckpointError("The saved outline file is incomplete.")

    if data.get("source_sha256") != source_sha256:
        raise CheckpointError(
            f"The saved outline in '{path.parent}' was made from a different document. "
            "Delete that folder to start over."
        )

    expected = {"modules": size.modules, "lessons_per_module": size.lessons_per_module}

    if data.get("size") != expected:
        raise CheckpointError(
            f"The saved outline in '{path.parent}' was made for a different course size. "
            "Use the same size, or delete that folder to start over."
        )

    return data["outline"]
