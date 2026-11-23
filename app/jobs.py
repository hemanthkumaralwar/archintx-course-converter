"""
jobs.py

WHAT: Runs conversions for the web app in the background, one at a time, and
      keeps each job's progress and result in memory.

WHY:  A conversion takes minutes, longer than a web request should wait. One
      job at a time keeps the free Gemini quota safe. Each job works in its own
      temporary folder, which is deleted when the job ends; only the finished
      course JSON is kept, in memory, for an hour.

LIMITS: one server process (jobs are not shared between processes) and no
        persistence: a restart forgets running and finished jobs.
"""

import dataclasses
import logging
import shutil
import tempfile
import threading
import time
import uuid
from dataclasses import dataclass
from pathlib import Path

from converter.exceptions import CourseGenerationError, ExtractionError, GenerationError
from converter.json_utils import load_json
from converter.retry import set_retry_listener

logger = logging.getLogger(__name__)

# How long a finished job's result can be downloaded, and how many are kept.
JOB_RETENTION_SECONDS = 60 * 60
MAX_KEPT_JOBS = 20

# Messages shown to users. Only a file's own extraction message (which names
# the file, never a folder) is shown as it is; everything else is generic.
AI_FAILED = (
    "The AI service did not return a usable answer after several attempts. "
    "Please try again in a few minutes."
)
GENERIC_FAILURE = (
    "The conversion failed. Please try again; if it keeps failing, report job {job_id}."
)


@dataclass
class Job:
    """
    One conversion. `result` is the finished course JSON once state is "done".

    steps:  every finished piece so far, in order: {"label", "reused"}. The
            page shows them as a list, so none is missed between two polls.
    notice: a "trying again" message while a step is being retried, else "".
    """

    id: str
    file_name: str
    state: str = "queued"  # queued, running, done, failed
    done: int = 0
    total: int = 0
    label: str = ""
    steps: list = dataclasses.field(default_factory=list)
    notice: str = ""
    error: str = ""
    result: dict = None
    finished_at: float = None


def retry_message(notice):
    """
    WHAT: The page's "trying again" message for one retry.

    WHY:  Built from counts only. The failure's own text is not shown: a
          validation message can quote the model's answer.
    """
    attempt = f"try {notice.attempt} of {notice.max_attempts}"

    if notice.service_failed:
        return (
            f"The AI service is busy or did not answer ({attempt}). "
            f"Trying again in {round(notice.wait_seconds)} s. Nothing is lost."
        )

    return f"The AI's answer did not pass the checks ({attempt}). Asking again."


def public_message(error, job_id):
    """The message a user sees for a failed job: never a path, key or traceback."""
    if isinstance(error, ExtractionError):
        return str(error)
    if isinstance(error, GenerationError):
        return AI_FAILED
    return GENERIC_FAILURE.format(job_id=job_id)


class JobRunner:
    """
    WHAT: Starts jobs on a background thread, one at a time, and answers
          questions about them.

    WHY:  `convert_fn` and `clock` are passed in, so tests can use a fake
          conversion and a fake clock.
    """

    def __init__(self, convert_fn, work_root, clock=time.monotonic):
        self._convert = convert_fn
        self._work_root = Path(work_root)
        self._clock = clock
        self._jobs = {}
        self._lock = threading.Lock()  # guards _jobs, _busy and every Job's fields
        self._busy = False

    def start(self, file_name, data, provider, options):
        """
        WHAT: Start converting `data` (the uploaded bytes) in the background.

        RETURNS:
            The new job's id, or None if another job is still running.
        """
        with self._lock:
            if self._busy:
                return None
            self._busy = True
            self._prune()
            job = Job(id=uuid.uuid4().hex, file_name=file_name)
            self._jobs[job.id] = job

        logger.info("Job %s started: %d bytes", job.id, len(data))
        thread = threading.Thread(
            target=self._run, args=(job, data, provider, options), daemon=True
        )
        thread.start()
        return job.id

    def get(self, job_id):
        """Return a copy of the job (safe to read while it runs), or None."""
        with self._lock:
            job = self._jobs.get(job_id)
            return dataclasses.replace(job, steps=list(job.steps)) if job else None

    def _run(self, job, data, provider, options):
        self._update(job, state="running")
        set_retry_listener(lambda notice: self._update(job, notice=retry_message(notice)))

        try:
            outcome = self._convert_in_temp_folder(job, data, provider, options)
        finally:
            set_retry_listener(None)

        outcome["notice"] = ""

        # The final state is set only now, after the temp folder is gone, so
        # "done" or "failed" always means the job is completely finished.
        with self._lock:
            for name, value in outcome.items():
                setattr(job, name, value)
            job.finished_at = self._clock()
            self._busy = False

        logger.info("Job %s finished: %s", job.id, outcome["state"])

    def _convert_in_temp_folder(self, job, data, provider, options):
        """
        WHAT: Convert in a fresh temp folder, delete the folder, and return the
              job's final fields: {"state", "result"} or {"state", "error"}.
        """
        self._work_root.mkdir(parents=True, exist_ok=True)
        work = Path(tempfile.mkdtemp(dir=self._work_root))

        try:
            path = work / job.file_name
            path.write_bytes(data)
            options = dataclasses.replace(options, output_root=work / "output")
            course_file = self._convert(path, provider, options, self._progress(job))
            return {"state": "done", "result": load_json(course_file)}
        except CourseGenerationError as exc:
            logger.warning("Job %s failed: %s", job.id, type(exc).__name__)
            return {"state": "failed", "error": public_message(exc, job.id)}
        except Exception:
            # A bug: keep the traceback in the server log, show a generic message.
            logger.exception("Job %s failed unexpectedly", job.id)
            return {"state": "failed", "error": public_message(None, job.id)}
        finally:
            shutil.rmtree(work, ignore_errors=True)

    def _progress(self, job):
        def report(event):
            with self._lock:
                job.done, job.total, job.label = event.done, event.total, event.label
                job.steps.append({"label": event.label, "reused": event.reused})
                job.notice = ""  # the retried step has finished

        return report

    def _update(self, job, **fields):
        with self._lock:
            for name, value in fields.items():
                setattr(job, name, value)

    def _prune(self):
        """Forget finished jobs older than the retention time, and the oldest beyond the cap."""
        now = self._clock()
        finished = sorted(
            (job for job in self._jobs.values() if job.finished_at is not None),
            key=lambda job: job.finished_at,
        )
        expired = [job for job in finished if now - job.finished_at > JOB_RETENTION_SECONDS]
        overflow = finished[: max(0, len(finished) - MAX_KEPT_JOBS + 1)]

        for job in {job.id: job for job in expired + overflow}.values():
            del self._jobs[job.id]
