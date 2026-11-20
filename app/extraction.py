"""
extraction.py

WHAT: Reads an uploaded document in a separate process that is stopped after a
      time limit.

WHY:  Uploaded files are untrusted. A crafted PDF can make the PDF library run
      for a very long time; a thread could not be stopped, but a process can.
      The size limits in converter/extractors.py still apply inside the process.
"""

import multiprocessing
from pathlib import Path

from converter.exceptions import ExtractionError
from converter.extractors import DEFAULT_LIMITS, extract_blocks

# Seconds one document may take to read. The 200-page limit keeps normal
# documents far below this.
EXTRACTION_SECONDS = 60


def read_in_child(path, limits, connection):
    """
    WHAT: Run in the child process: read the file and send back the result.

    SENDS:
        ("ok", blocks), or ("error", message) for an ExtractionError, or
        ("error", None) for anything unexpected (the parent shows a generic message).
    """
    try:
        connection.send(("ok", extract_blocks(path, limits)))
    except ExtractionError as exc:
        connection.send(("error", str(exc)))
    except Exception:  # The parent only needs to know that reading failed.
        connection.send(("error", None))
    finally:
        connection.close()


def extract_with_time_limit(
    path, limits=DEFAULT_LIMITS, seconds=EXTRACTION_SECONDS, target=read_in_child
):
    """
    WHAT: extract_blocks(path, limits), run in a new process that is stopped
          after `seconds`.

    PARAMETERS:
        target: the function the child runs; tests pass a slow or crashing one.

    RAISES:
        ExtractionError: if reading fails, takes too long, or the child process dies.
    """
    name = Path(path).name
    context = multiprocessing.get_context("spawn")  # the same on Windows and Linux
    receiver, sender = context.Pipe(duplex=False)
    process = context.Process(target=target, args=(path, limits, sender), daemon=True)
    process.start()
    sender.close()  # only the child writes; this lets recv() see a dead child

    try:
        if not receiver.poll(seconds):
            raise ExtractionError(f"'{name}' took too long to read (more than {seconds} seconds).")
        status, value = receiver.recv()
    except EOFError as exc:
        raise ExtractionError(f"'{name}' could not be read.") from exc
    finally:
        if process.is_alive():
            process.terminate()
        process.join(timeout=5)
        receiver.close()

    if status == "error":
        raise ExtractionError(value or f"'{name}' could not be read.")

    return value
