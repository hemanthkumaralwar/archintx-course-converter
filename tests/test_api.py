"""
Tests for app/main.py and app/jobs.py through the HTTP API, with FakeProvider.

The conversion runs in-process (no extraction child process) to keep these
tests fast; app/extraction.py has its own tests in test_extraction.py.
"""

import functools
import logging
import socket
import threading
import time

import pytest
from fastapi.testclient import TestClient

from app.main import create_app
from converter.config import Settings
from converter.convert import convert
from converter.exceptions import ConfigurationError, GenerationError
from converter.extractors import extract_blocks
from converter.planner import SizeRequest
from converter.validation import collect_errors
from tests.fakes import FakeProvider
from tests.sample_course import SAMPLE_INPUT, SCHEMAS, conversion_answers

CODE = "demo-code-123"
API_KEY = "sk-visitor-key-not-real"


@pytest.fixture(autouse=True)
def no_network(monkeypatch):
    """Fail any connection that leaves this machine. Loopback is allowed: on
    Windows the test client's event loop connects a socket pair to 127.0.0.1."""
    real_connect = socket.socket.connect

    def local_only(sock, address):
        if isinstance(address, tuple) and address[0] not in ("127.0.0.1", "::1", "localhost"):
            raise AssertionError("tests must not use the network")
        return real_connect(sock, address)

    monkeypatch.setattr(socket.socket, "connect", local_only)


class ProviderFactory:
    """Stands in for providers.get_provider and records what it was given."""

    def __init__(self, provider):
        self.provider = provider
        self.calls = []

    def __call__(self, settings, api_key=None):
        self.calls.append((settings.llm_provider, api_key))
        return self.provider


@pytest.fixture
def work_root(tmp_path):
    return tmp_path / "jobs"


def make_client(work_root, provider=None, convert_fn=None, code=CODE):
    factory = ProviderFactory(provider or FakeProvider(conversion_answers()))
    app = create_app(
        settings=Settings(demo_access_code=code),
        provider_factory=factory,
        convert_fn=convert_fn or functools.partial(convert, extract=extract_blocks),
        work_root=work_root,
    )
    return TestClient(app), factory


def upload(client, name="python-basics.txt", data=None, code=CODE, **fields):
    headers = {"X-Access-Code": code} if code is not None else {}
    headers.update(fields.pop("headers", {}))
    form = {"modules": "2", "lessons": "3", **{k: str(v) for k, v in fields.items()}}
    form = {k: v for k, v in form.items() if v != "None"}
    content = data if data is not None else SAMPLE_INPUT.read_bytes()
    return client.post("/api/convert", files={"file": (name, content)}, data=form, headers=headers)


def wait_for(client, job_id, seconds=30):
    """Poll the job until it finishes (the conversion runs on a background thread)."""
    deadline = time.monotonic() + seconds
    while time.monotonic() < deadline:
        status = client.get(f"/api/jobs/{job_id}", headers={"X-Access-Code": CODE}).json()
        if status["state"] in ("done", "failed"):
            return status
        time.sleep(0.05)
    raise AssertionError("job did not finish")


# ---------------------------------------------------------------------------
# The happy path
# ---------------------------------------------------------------------------


def test_upload_progress_and_download(work_root):
    client, _ = make_client(work_root)

    response = upload(client)
    assert response.status_code == 202
    job_id = response.json()["jobId"]
    assert len(job_id) == 32  # a random uuid4

    status = wait_for(client, job_id)
    steps = status.pop("steps")
    assert status == {
        "jobId": job_id,
        "state": "done",
        "done": 10,
        "total": 10,
        "label": "Lesson 2.3: Putting It Together",
        "notice": "",
        "error": "",
    }
    assert len(steps) == 10
    assert steps[0] == {"label": "Course outline", "reused": False}
    assert steps[-1] == {"label": "Lesson 2.3: Putting It Together", "reused": False}

    download = client.get(f"/api/jobs/{job_id}/download", headers={"X-Access-Code": CODE})
    assert download.status_code == 200
    assert 'filename="python_basics-course.json"' in download.headers["content-disposition"]
    assert collect_errors(SCHEMAS.course_validator, download.json()) == []


def test_temp_folder_is_empty_after_a_job(work_root):
    client, _ = make_client(work_root)

    wait_for(client, upload(client).json()["jobId"])

    assert list(work_root.iterdir()) == []


def test_health_needs_no_access_code(work_root):
    client, _ = make_client(work_root)

    assert client.get("/healthz").json() == {"status": "ok"}


# ---------------------------------------------------------------------------
# Upload limits
# ---------------------------------------------------------------------------


def test_file_over_10_mb_is_refused_before_reading(work_root):
    client, factory = make_client(work_root)

    response = upload(client, data=b"x" * (11 * 1024 * 1024))

    assert response.status_code == 413
    assert response.json() == {"error": "The file is larger than 10 MB."}
    assert factory.calls == []  # stopped before the endpoint ran


def test_file_just_over_10_mb_inside_the_form_allowance_is_refused(work_root):
    client, _ = make_client(work_root)

    response = upload(client, data=b"x" * (10 * 1024 * 1024 + 10))

    assert response.status_code == 413


def test_upload_without_a_declared_size_is_refused(work_root):
    client, _ = make_client(work_root)

    def body():
        yield b"--x\r\n"

    response = client.post(
        "/api/convert",
        content=body(),
        headers={"X-Access-Code": CODE, "Content-Type": "multipart/form-data; boundary=x"},
    )

    assert response.status_code == 411


@pytest.mark.parametrize("name", ["notes.rtf", "notes.doc", "notes", "../../etc/passwd"])
def test_unsupported_file_type_is_refused(work_root, name):
    client, factory = make_client(work_root)

    response = upload(client, name=name)

    assert response.status_code == 415
    assert response.json() == {"error": "Only .txt, .docx and .pdf files can be converted."}


def test_unsafe_file_name_is_cleaned(work_root):
    client, _ = make_client(work_root)

    job_id = upload(client, name="../../evil name.txt").json()["jobId"]
    wait_for(client, job_id)
    download = client.get(f"/api/jobs/{job_id}/download", headers={"X-Access-Code": CODE})

    assert 'filename="evil_name-course.json"' in download.headers["content-disposition"]


# ---------------------------------------------------------------------------
# Access code
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("code", [None, "", "wrong-code", CODE + "x"])
def test_missing_or_wrong_access_code_is_refused(work_root, code):
    client, factory = make_client(work_root)

    response = upload(client, code=code)

    assert response.status_code == 401
    assert response.json() == {"error": "The access code is missing or wrong."}
    assert factory.calls == []


def test_job_routes_also_need_the_access_code(work_root):
    client, _ = make_client(work_root)
    job_id = upload(client).json()["jobId"]
    wait_for(client, job_id)

    assert client.get(f"/api/jobs/{job_id}").status_code == 401
    assert client.get(f"/api/jobs/{job_id}/download").status_code == 401


def test_conversions_are_off_when_no_code_is_configured(work_root):
    client, _ = make_client(work_root, code="")

    response = upload(client, code="")

    assert response.status_code == 503
    assert "no access code is set" in response.json()["error"]


# ---------------------------------------------------------------------------
# One job at a time
# ---------------------------------------------------------------------------


def test_second_job_while_one_is_running_is_refused(work_root):
    release = threading.Event()

    def blocking_convert(path, provider, options, progress):
        release.wait(10)
        raise GenerationError("stopped by the test")

    client, _ = make_client(work_root, convert_fn=blocking_convert)
    first = upload(client)

    second = upload(client)
    release.set()

    assert first.status_code == 202
    assert second.status_code == 429
    assert second.json() == {"error": "Another conversion is running. Try again when it finishes."}
    wait_for(client, first.json()["jobId"])
    assert upload(client).status_code == 202  # free again once the first job ends


# ---------------------------------------------------------------------------
# Options
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("fields", "message"),
    [
        ({"modules": 99}, "The number of modules must be from 1 to 30 (got 99)."),
        ({"hours": 33}, "The number of course hours must be from 1 to 32 (got 33)."),
        (
            {"hours": 3},
            "Choose the course duration or both counts, not all three: "
            "with modules and lessons chosen, the duration follows from them.",
        ),
        ({"provider": "claude"}, "Unknown provider. Use gemini or openai."),
        ({"modules": "two"}, "The request is missing the file or has an invalid option."),
    ],
)
def test_bad_options_get_a_short_message(work_root, fields, message):
    client, _ = make_client(work_root)

    response = upload(client, **fields)

    assert response.status_code == 400
    assert response.json() == {"error": message}
    assert "two" not in response.text  # the submitted value is not echoed back


def test_missing_api_key_is_reported_by_name(work_root):
    def no_key(settings, api_key=None):
        raise ConfigurationError("GEMINI_API_KEY is missing. Add it to your .env file.")

    app = create_app(
        settings=Settings(demo_access_code=CODE), provider_factory=no_key, work_root=work_root
    )

    response = upload(TestClient(app))

    assert response.status_code == 400
    assert response.json() == {"error": "GEMINI_API_KEY is missing. Add it to your .env file."}


def test_provider_and_pasted_key_reach_the_provider_factory(work_root):
    client, factory = make_client(work_root)

    response = upload(client, provider="openai", headers={"X-API-Key": f"  {API_KEY} "})
    wait_for(client, response.json()["jobId"])

    assert factory.calls == [("openai", API_KEY)]


def test_pasted_key_never_appears_in_the_log(work_root, caplog):
    client, _ = make_client(work_root)

    with caplog.at_level(logging.DEBUG):
        job_id = upload(client, headers={"X-API-Key": API_KEY}).json()["jobId"]
        wait_for(client, job_id)

    assert "Job" in caplog.text  # job events are logged...
    assert API_KEY not in caplog.text  # ...but never the key


def test_automatic_size_when_no_size_is_sent(work_root):
    seen = {}

    def recording_convert(path, provider, options, progress):
        seen["size"] = options.size
        raise GenerationError("stop")

    client, _ = make_client(work_root, convert_fn=recording_convert)
    wait_for(client, upload(client, modules=None, lessons=None).json()["jobId"])

    assert seen["size"] is None


def test_one_count_and_hours_reach_the_conversion(work_root):
    seen = {}

    def recording_convert(path, provider, options, progress):
        seen["size"] = options.size
        raise GenerationError("stop")

    client, _ = make_client(work_root, convert_fn=recording_convert)
    wait_for(client, upload(client, modules=2, lessons=None, hours=3).json()["jobId"])

    assert seen["size"] == SizeRequest(modules=2, lessons_per_module=None, hours=3)


@pytest.mark.parametrize(
    ("query", "expected"),
    [
        (
            "modules=2&lessons=3",
            {
                "modules": 2,
                "lessons": 3,
                "totalLessons": 6,
                "hours": 3.0,
                "apiCalls": 10,
                "minutes": 2,
            },
        ),
        (
            "modules=2&hours=3",
            {
                "modules": 2,
                "lessons": 3,
                "totalLessons": 6,
                "hours": 3.0,
                "apiCalls": 10,
                "minutes": 2,
            },
        ),
        (
            "hours=4",
            {
                "modules": 1,
                "lessons": 8,
                "totalLessons": 8,
                "hours": 4.0,
                "apiCalls": 11,
                "minutes": 2,
            },
        ),
        (
            "lessons=4",
            {
                "modules": None,
                "lessons": 4,
                "totalLessons": None,
                "hours": None,
                "apiCalls": None,
                "minutes": None,
            },
        ),
        (
            "",
            {
                "modules": None,
                "lessons": None,
                "totalLessons": None,
                "hours": None,
                "apiCalls": None,
                "minutes": None,
            },
        ),
    ],
)
def test_size_preview_needs_no_access_code(work_root, query, expected):
    client, factory = make_client(work_root)

    response = client.get(f"/api/size?{query}")

    assert response.status_code == 200
    assert response.json() == expected
    assert factory.calls == []  # arithmetic only: no AI provider is made


def test_size_preview_rejects_all_three(work_root):
    client, _ = make_client(work_root)

    response = client.get("/api/size?modules=2&lessons=3&hours=3")

    assert response.status_code == 400
    assert "not all three" in response.json()["error"]


# ---------------------------------------------------------------------------
# Failed jobs and errors
# ---------------------------------------------------------------------------


def test_unreadable_file_fails_with_its_own_message_and_no_path(work_root):
    client, _ = make_client(work_root)

    status = wait_for(
        client, upload(client, name="broken.pdf", data=b"%PDF-1.7 broken").json()["jobId"]
    )

    assert status["state"] == "failed"
    assert status["error"] == "'broken.pdf' could not be read as a PDF."
    assert list(work_root.iterdir()) == []


@pytest.mark.parametrize(
    ("error", "message"),
    [
        (
            GenerationError("503 at C:\\secret\\path"),
            "The AI service did not return a usable answer",
        ),
        (ValueError("bug at C:\\secret\\path"), "The conversion failed. Please try again"),
        (
            ConfigurationError("Could not create folders under C:\\secret\\path"),
            "The conversion failed",
        ),
    ],
    ids=["ai-service", "bug", "internal-setup"],
)
def test_other_failures_show_no_internals(work_root, error, message):
    def failing_convert(path, provider, options, progress):
        raise error

    client, _ = make_client(work_root, convert_fn=failing_convert)
    job_id = upload(client).json()["jobId"]

    status = wait_for(client, job_id)

    assert status["state"] == "failed"
    assert status["error"].startswith(message)
    assert "secret" not in status["error"] and "Traceback" not in status["error"]
    assert list(work_root.iterdir()) == []


def test_unknown_job_and_unfinished_download(work_root):
    release = threading.Event()

    def blocking_convert(path, provider, options, progress):
        release.wait(10)
        raise GenerationError("stop")

    client, _ = make_client(work_root, convert_fn=blocking_convert)
    headers = {"X-Access-Code": CODE}
    job_id = upload(client).json()["jobId"]

    assert client.get(f"/api/jobs/{job_id}/download", headers=headers).status_code == 409
    release.set()
    wait_for(client, job_id)
    assert client.get("/api/jobs/not-a-job", headers=headers).status_code == 404


def test_unexpected_server_error_is_generic(work_root):
    def broken_factory(settings, api_key=None):
        raise RuntimeError("internal detail C:\\secret")

    app = create_app(
        settings=Settings(demo_access_code=CODE),
        provider_factory=broken_factory,
        work_root=work_root,
    )
    client = TestClient(app, raise_server_exceptions=False)

    response = upload(client)

    assert response.status_code == 500
    assert response.json() == {"error": "Something went wrong on the server."}
