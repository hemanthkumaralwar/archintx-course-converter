"""Tests for app/jobs.py: keeping and forgetting finished jobs."""

import threading
import time

from app.jobs import JOB_RETENTION_SECONDS, MAX_KEPT_JOBS, JobRunner, retry_message
from converter.convert import ConversionOptions
from converter.exceptions import GenerationError
from converter.pipeline import Progress
from converter.retry import RetryNotice, run_with_retries


class Clock:
    def __init__(self):
        self.now = 1000.0

    def __call__(self):
        return self.now


def failing_convert(path, provider, options, progress):
    raise GenerationError("stop")


def run_job(runner):
    job_id = runner.start("a.txt", b"text", provider=None, options=ConversionOptions())
    deadline = time.monotonic() + 10
    while runner.get(job_id).finished_at is None:
        assert time.monotonic() < deadline, "job did not finish"
        time.sleep(0.01)
    return job_id


def test_finished_jobs_are_forgotten_after_an_hour(tmp_path):
    clock = Clock()
    runner = JobRunner(failing_convert, tmp_path, clock=clock)
    old = run_job(runner)

    clock.now += JOB_RETENTION_SECONDS + 1
    new = run_job(runner)  # starting a job removes expired ones

    assert runner.get(old) is None
    assert runner.get(new).state == "failed"


def test_only_the_newest_finished_jobs_are_kept(tmp_path):
    clock = Clock()
    runner = JobRunner(failing_convert, tmp_path, clock=clock)
    ids = []
    for _ in range(MAX_KEPT_JOBS + 2):
        clock.now += 1
        ids.append(run_job(runner))

    kept = [job_id for job_id in ids if runner.get(job_id) is not None]

    assert len(kept) == MAX_KEPT_JOBS
    assert kept == ids[-MAX_KEPT_JOBS:]


def test_get_returns_a_copy(tmp_path):
    runner = JobRunner(failing_convert, tmp_path)
    job_id = run_job(runner)

    runner.get(job_id).state = "changed"

    assert runner.get(job_id).state == "failed"


def test_retry_message_for_a_busy_service():
    message = retry_message(RetryNotice(1, 3, 15, service_failed=True))

    assert message == (
        "The AI service is busy or did not answer (try 1 of 3). "
        "Trying again in 15 s. Nothing is lost."
    )


def test_retry_message_for_an_answer_that_failed_the_checks():
    message = retry_message(RetryNotice(2, 3, 0, service_failed=False))

    assert message == "The AI's answer did not pass the checks (try 2 of 3). Asking again."


def test_notice_is_shown_while_retrying_and_cleared_after(tmp_path):
    started = threading.Event()
    job_ids, seen = [], {}

    def convert_with_a_retry(path, provider, options, progress):
        started.wait(5)
        outcomes = [GenerationError("503")]

        def attempt(previous_errors, attempt_number):
            if outcomes:
                raise outcomes.pop()
            seen["during"] = runner.get(job_ids[0]).notice
            return "ok"

        run_with_retries("Step", attempt, 3, 0, sleep=lambda seconds: None)
        progress(Progress(1, 1, "Step"))
        raise GenerationError("stop")

    runner = JobRunner(convert_with_a_retry, tmp_path)
    job_ids.append(runner.start("a.txt", b"text", provider=None, options=ConversionOptions()))
    started.set()
    deadline = time.monotonic() + 10
    while runner.get(job_ids[0]).finished_at is None:
        assert time.monotonic() < deadline, "job did not finish"
        time.sleep(0.01)

    assert seen["during"].startswith("The AI service is busy")
    job = runner.get(job_ids[0])
    assert job.notice == ""
    assert job.steps == [{"label": "Step", "reused": False}]
