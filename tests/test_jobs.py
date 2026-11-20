"""Tests for app/jobs.py: keeping and forgetting finished jobs."""

import time

from app.jobs import JOB_RETENTION_SECONDS, MAX_KEPT_JOBS, JobRunner
from converter.convert import ConversionOptions
from converter.exceptions import GenerationError


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
