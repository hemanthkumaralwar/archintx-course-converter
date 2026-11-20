"""
main.py

WHAT: The web API for the converter:
        POST /api/convert                 upload a file and options; starts a job
        GET  /api/jobs/{job_id}           the job's state and progress
        GET  /api/jobs/{job_id}/download the finished course JSON
        GET  /healthz                     liveness check (no access code needed)
        GET  /                            the upload page (app/static/)
        GET  /sample/python-basics.txt    the sample document, for a quick try

      Start it with:  uvicorn app.main:create_app --factory

WHY:  Every /api call needs the access code (X-Access-Code header), so
      strangers cannot use up the Gemini quota. Uploads are size-checked from
      Content-Length before the body is read. Error responses are short and
      never include paths, keys or tracebacks.
"""

import dataclasses
import functools
import hmac
import logging
import tempfile
from pathlib import Path
from typing import Annotated

from fastapi import Depends, FastAPI, File, Form, Header, HTTPException, Request, UploadFile
from fastapi.exceptions import RequestValidationError
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from starlette.exceptions import HTTPException as StarletteHTTPException

from converter.config import PROJECT_ROOT, load_settings
from converter.convert import ConversionOptions, convert, safe_slug
from converter.exceptions import ConfigurationError
from converter.extractors import DEFAULT_LIMITS, READERS
from converter.planner import CourseSize, check_course_size
from converter.providers import PROVIDER_FACTORIES, get_provider

from .extraction import extract_with_time_limit
from .jobs import JobRunner

logger = logging.getLogger(__name__)

# Room for the multipart form around the file (field names, boundaries, options).
FORM_OVERHEAD_BYTES = 64 * 1024
MAX_REQUEST_BYTES = DEFAULT_LIMITS.max_file_bytes + FORM_OVERHEAD_BYTES

DEFAULT_WORK_ROOT = Path(tempfile.gettempdir()) / "archintx-jobs"

STATIC_DIR = Path(__file__).resolve().parent / "static"
SAMPLE_DOCUMENT = PROJECT_ROOT / "samples" / "inputs" / "python-basics.txt"

# Sent with every response. The page uses only its own files (no inline
# script or style, nothing from other sites), so the policy can be strict:
# injected HTML could not run scripts, and the page cannot be framed.
SECURITY_HEADERS = {
    "Content-Security-Policy": (
        "default-src 'self'; base-uri 'none'; form-action 'self'; frame-ancestors 'none'"
    ),
    "X-Content-Type-Options": "nosniff",
    "X-Frame-Options": "DENY",
    "Referrer-Policy": "no-referrer",
}


def create_app(
    settings=None,
    provider_factory=get_provider,
    convert_fn=None,
    work_root=DEFAULT_WORK_ROOT,
):
    """
    WHAT: Build the FastAPI app.

    WHY:  Everything the app depends on is a parameter, so tests can pass fake
          settings, a fake provider and a fast in-process conversion. Settings
          are read once, here.
    """
    settings = settings or load_settings()
    runner = JobRunner(
        convert_fn or functools.partial(convert, extract=extract_with_time_limit), work_root
    )
    # No interactive API docs: nothing on the public site that is not needed.
    app = FastAPI(
        title="Archintx Course Converter", docs_url=None, redoc_url=None, openapi_url=None
    )
    _add_error_handlers(app)
    app.middleware("http")(_limit_upload_size)
    app.middleware("http")(_add_security_headers)
    app.mount("/static", StaticFiles(directory=STATIC_DIR), name="static")

    @app.get("/", include_in_schema=False)
    def page():
        return FileResponse(STATIC_DIR / "index.html")

    @app.get("/sample/python-basics.txt", include_in_schema=False)
    def sample_document():
        return FileResponse(SAMPLE_DOCUMENT, media_type="text/plain; charset=utf-8")

    @app.get("/healthz")
    def health():
        return {"status": "ok"}

    access = [Depends(access_check(settings))]
    _add_conversion_routes(app, settings, provider_factory, runner, access)
    _add_job_routes(app, runner, access)
    return app


def access_check(settings):
    """
    WHAT: A FastAPI dependency that requires the X-Access-Code header.

    WHY:  Fails closed: with no code configured, conversions are switched off
          rather than open to anyone. compare_digest takes the same time
          whatever the input, so the code cannot be guessed by timing.
    """

    def require_access_code(x_access_code: Annotated[str, Header()] = ""):
        if not settings.demo_access_code:
            raise HTTPException(
                503, "Conversions are switched off: no access code is set on the server."
            )
        if not hmac.compare_digest(x_access_code.encode(), settings.demo_access_code.encode()):
            raise HTTPException(401, "The access code is missing or wrong.")

    return require_access_code


def _add_conversion_routes(app, settings, provider_factory, runner, access):
    @app.post("/api/convert", status_code=202, dependencies=access)
    async def start_conversion(
        file: Annotated[UploadFile, File()],
        modules: Annotated[int | None, Form()] = None,
        lessons: Annotated[int | None, Form()] = None,
        provider: Annotated[str | None, Form()] = None,
        x_api_key: Annotated[str, Header()] = "",
    ):
        file_name = upload_name(file.filename)
        size = requested_size(modules, lessons)
        llm = make_provider(settings, provider_factory, provider, x_api_key)
        data = await file.read(DEFAULT_LIMITS.max_file_bytes + 1)

        if len(data) > DEFAULT_LIMITS.max_file_bytes:
            raise HTTPException(413, "The file is larger than 10 MB.")

        job_id = runner.start(file_name, data, llm, ConversionOptions(size=size))

        if job_id is None:
            raise HTTPException(429, "Another conversion is running. Try again when it finishes.")

        return {"jobId": job_id}


def _add_job_routes(app, runner, access):
    @app.get("/api/jobs/{job_id}", dependencies=access)
    def job_status(job_id: str):
        job = find_job(runner, job_id)
        return {
            "jobId": job.id,
            "state": job.state,
            "done": job.done,
            "total": job.total,
            "label": job.label,
            "error": job.error,
        }

    @app.get("/api/jobs/{job_id}/download", dependencies=access)
    def download(job_id: str):
        job = find_job(runner, job_id)

        if job.state != "done":
            raise HTTPException(409, "The course is not ready yet.")

        name = f"{Path(job.file_name).stem}-course.json"
        return JSONResponse(
            job.result, headers={"Content-Disposition": f'attachment; filename="{name}"'}
        )


async def _limit_upload_size(request: Request, call_next):
    """
    WHAT: Reject an upload whose declared size is too large, or not declared,
          before its body is read.

    WHY:  The form parser reads the whole body before the endpoint runs, so a
          check inside the endpoint would come too late to protect memory and disk.
    """
    if request.method == "POST" and request.url.path == "/api/convert":
        length = request.headers.get("content-length")

        if length is None or not length.isdigit():
            return _error(411, "The upload must state its size (Content-Length).")

        if int(length) > MAX_REQUEST_BYTES:
            return _error(413, "The file is larger than 10 MB.")

    return await call_next(request)


def upload_name(filename):
    """
    WHAT: A safe name for the uploaded file: a cleaned stem plus its extension.

    WHY:  The browser's file name is untrusted (it could contain "../" or
          control characters), so only letters, digits and "_" of its stem are kept.

    RAISES:
        HTTPException(415): if the extension is not .txt, .docx or .pdf.
    """
    path = Path(filename or "")
    suffix = path.suffix.lower()

    if suffix not in READERS:
        raise HTTPException(415, "Only .txt, .docx and .pdf files can be converted.")

    return safe_slug(path.stem, fallback="document") + suffix


def requested_size(modules, lessons):
    """The CourseSize asked for, or None for automatic size."""
    if modules is None and lessons is None:
        return None

    if modules is None or lessons is None:
        raise HTTPException(400, "Give both the number of modules and lessons, or neither.")

    size = CourseSize(modules, lessons)

    try:
        check_course_size(size)
    except ConfigurationError as exc:
        raise HTTPException(400, str(exc)) from exc

    return size


def make_provider(settings, provider_factory, provider_name, api_key):
    """
    WHAT: The LLM provider for one job, using the visitor's pasted key if given.

    WHY:  The pasted key goes straight to the provider and lives only as long
          as the job; it is never logged or stored.
    """
    if provider_name:
        if provider_name not in PROVIDER_FACTORIES:
            raise HTTPException(400, "Unknown provider. Use gemini or openai.")
        settings = dataclasses.replace(settings, llm_provider=provider_name)

    try:
        return provider_factory(settings, api_key=api_key.strip() or None)
    except ConfigurationError as exc:
        # These messages name a setting (such as GEMINI_API_KEY), never a key value.
        raise HTTPException(400, str(exc)) from exc


def find_job(runner, job_id):
    job = runner.get(job_id)

    if job is None:
        raise HTTPException(404, "No such job. Finished jobs are kept for one hour.")

    return job


async def _add_security_headers(request: Request, call_next):
    response = await call_next(request)
    response.headers.update(SECURITY_HEADERS)
    return response


def _error(status, message):
    return JSONResponse({"error": message}, status_code=status)


def _add_error_handlers(app):
    """Every error becomes {"error": "<short message>"}: no echo of the request, no traceback."""

    @app.exception_handler(StarletteHTTPException)
    async def http_error(request, exc):
        return _error(exc.status_code, str(exc.detail))

    @app.exception_handler(RequestValidationError)
    async def invalid_request(request, exc):
        # FastAPI's default reply repeats the submitted values; this one does not.
        return _error(400, "The request is missing the file or has an invalid option.")

    @app.exception_handler(Exception)
    async def unexpected(request, exc):
        logger.exception("Unexpected error on %s", request.url.path)
        return _error(500, "Something went wrong on the server.")
