"""
cli.py

WHAT: Command-line entry point of the converter:

        python -m converter.cli notes.pdf
        python -m converter.cli notes.docx --modules 2 --lessons 3 --provider gemini -o course.json

      Without --modules and --lessons, the course size is chosen from the
      document's length.

EXIT CODES:
    0    success
    1    an expected error (shown as one short message)
    2    wrong command-line arguments
    130  stopped with Ctrl+C (saved work is kept; run the same command to resume)
"""

import argparse
import dataclasses
import logging
import sys

from .config import load_settings
from .convert import ConversionOptions, convert
from .exceptions import CourseGenerationError
from .json_utils import load_json, save_json
from .planner import CourseSize
from .providers import PROVIDER_FACTORIES, get_provider


def print_progress(event):
    """Show one finished piece, such as "[3/8] Lesson 1.1: Variables (saved)"."""
    status = "already saved" if event.reused else "saved"
    print(f"[{event.done}/{event.total}] {event.label} ({status})")


def parse_arguments(argv=None):
    """
    WHAT: Read and check the command-line arguments.

    RAISES:
        SystemExit(2): through argparse, for missing or invalid arguments.
    """
    parser = argparse.ArgumentParser(
        prog="python -m converter.cli",
        description="Convert a .txt, .docx or .pdf file into course JSON.",
    )
    parser.add_argument("input", help="the .txt, .docx or .pdf file to convert")
    parser.add_argument("--modules", type=int, help="number of modules (use with --lessons)")
    parser.add_argument("--lessons", type=int, help="lessons per module (use with --modules)")
    parser.add_argument(
        "--provider",
        choices=sorted(PROVIDER_FACTORIES),
        help="LLM to use; overrides LLM_PROVIDER in .env",
    )
    parser.add_argument("-o", "--output", help="also save the finished course JSON to this file")
    parser.add_argument("--output-dir", help="folder for work in progress (default: output/)")
    args = parser.parse_args(argv)

    if (args.modules is None) != (args.lessons is None):
        parser.error(
            "--modules and --lessons must be given together (or neither, for automatic size)"
        )

    return args


def options_from(args):
    size = CourseSize(args.modules, args.lessons) if args.modules is not None else None
    options = ConversionOptions(size=size)

    if args.output_dir:
        options = dataclasses.replace(options, output_root=args.output_dir)

    return options


def main(argv=None):
    """
    WHAT: Parse arguments, run the conversion, and return an exit code.

    WHY:  Settings are read once, here. A missing API key or a bad file stops
          the run with one short message; unexpected bugs keep their traceback.
    """
    args = parse_arguments(argv)
    logging.basicConfig(level=logging.WARNING, format="%(levelname)s: %(message)s")

    try:
        settings = load_settings()

        if args.provider:
            settings = dataclasses.replace(settings, llm_provider=args.provider)

        course_file = convert(
            args.input, get_provider(settings), options_from(args), print_progress
        )

        if args.output:
            save_json(args.output, load_json(course_file))
            course_file = args.output

        print(f"\nDone. The course matches the schema: {course_file}")
        return 0

    except CourseGenerationError as exc:
        print(f"\nERROR: {exc}", file=sys.stderr)
        return 1

    except KeyboardInterrupt:
        print(
            "\nStopped. Finished parts are saved; run the same command again to continue.",
            file=sys.stderr,
        )
        return 130


if __name__ == "__main__":
    sys.exit(main())
