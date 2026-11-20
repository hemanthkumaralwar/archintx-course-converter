"""
generate.py

WHAT: Entry point of the original title-based course generator. Run it
      from the project root with either:
        python -m converter.generate
        python -m converter.generate --title "Intro to AI" --difficulty beginner --duration 31

WHY:  Keeping this file small makes the program start in one obvious place.
      It also decides how errors are shown: a short message for expected
      problems, and a full traceback only for unexpected bugs.
"""

import logging
import sys

from .config import load_settings
from .exceptions import CourseGenerationError
from .pipeline import run_pipeline
from .providers import get_provider
from .user_input import read_course_request


def print_progress(event):
    """Show one finished piece, such as "[3/19] Lesson 1.1: Variables (saved)"."""
    status = "already saved" if event.reused else "saved"
    print(f"[{event.done}/{event.total}] {event.label} ({status})")


def main(argv=None):
    """
    WHAT: Collect input, run the pipeline, and return an exit code.

    WHY:  Exit codes let scripts detect failure.
          0   success
          1   an expected error (shown as a short message)
          130 the user pressed Ctrl+C (progress is kept, so rerun to resume)

    RETURNS:
        An integer exit code.
    """
    # Warnings only (such as a retried step); progress is printed separately.
    logging.basicConfig(level=logging.WARNING, format="%(levelname)s: %(message)s")

    try:
        request = read_course_request(argv)
        # Settings are read once, here; a missing API key stops the run before any work.
        provider = get_provider(load_settings())
        output_file = run_pipeline(request, provider, print_progress)
        print(f"\nDone. The course matches the schema: {output_file}")
        return 0

    except CourseGenerationError as exc:
        print(f"\nERROR: {exc}", file=sys.stderr)
        return 1

    except KeyboardInterrupt:
        print(
            "\nInterrupted. Saved modules are kept; rerun with the same "
            "title, difficulty, and duration to resume.",
            file=sys.stderr,
        )
        return 130


if __name__ == "__main__":
    sys.exit(main())
