"""
Tests for the upload page (app/static/) and the security headers in app/main.py.

The page's JavaScript has no linter here (no Node.js), so these tests check the
security rules the page depends on directly in its files.
"""

import re

import pytest
from fastapi.testclient import TestClient

from app.main import STATIC_DIR, create_app
from converter.config import Settings
from tests.sample_course import SAMPLE_INPUT

CSP = "default-src 'self'; base-uri 'none'; form-action 'self'; frame-ancestors 'none'"


@pytest.fixture
def client(tmp_path):
    return TestClient(create_app(settings=Settings(demo_access_code="code"), work_root=tmp_path))


def html():
    return (STATIC_DIR / "index.html").read_text(encoding="utf-8")


def script():
    return (STATIC_DIR / "app.js").read_text(encoding="utf-8")


@pytest.mark.parametrize(
    ("path", "content_type"),
    [
        ("/", "text/html"),
        ("/static/app.js", "javascript"),
        ("/static/style.css", "text/css"),
        ("/sample/python-basics.txt", "text/plain"),
    ],
)
def test_page_files_are_served(client, path, content_type):
    response = client.get(path)

    assert response.status_code == 200
    assert content_type in response.headers["content-type"]


def test_sample_document_is_the_project_sample(client):
    assert client.get("/sample/python-basics.txt").content == SAMPLE_INPUT.read_bytes()


@pytest.mark.parametrize("path", ["/", "/static/app.js", "/healthz", "/api/jobs/x"])
def test_every_response_has_the_security_headers(client, path):
    headers = client.get(path).headers

    assert headers["content-security-policy"] == CSP
    assert headers["x-content-type-options"] == "nosniff"
    assert headers["x-frame-options"] == "DENY"
    assert headers["referrer-policy"] == "no-referrer"


def test_errors_before_the_endpoint_also_have_the_headers(client):
    response = client.post(
        "/api/convert", headers={"Content-Length": str(50 * 1024 * 1024)}, content=b""
    )

    assert response.status_code == 413
    assert response.headers["content-security-policy"] == CSP


def test_page_has_no_inline_script_or_style():
    page = html()

    scripts = re.findall(r"<script\b[^>]*>(.*?)</script>", page, re.DOTALL)
    assert scripts and all(body.strip() == "" for body in scripts)  # only <script src=...>
    assert "<style" not in page
    assert not re.search(r"\sstyle=", page)
    assert not re.search(r"\son[a-z]+=", page)  # no onclick= and similar


def test_page_loads_only_its_own_files():
    assert not re.search(r'(src|href)="(https?:)?//', html())


def test_script_never_inserts_html():
    code = script()

    for unsafe in ("innerHTML", "outerHTML", "insertAdjacentHTML", "document.write", "eval("):
        assert unsafe not in code


def test_script_does_not_store_the_code_or_key():
    code = script()

    assert "localStorage" not in code and "sessionStorage" not in code and "cookie" not in code


def test_secret_fields_are_password_fields():
    page = html()

    for field in ("access-code", "api-key"):
        assert re.search(rf'id="{field}" type="password" autocomplete="off"', page)


def test_page_warns_about_confidential_documents():
    assert "Do not upload confidential documents" in html()


def test_course_size_has_three_automatic_or_choose_fields():
    page = html()

    for field in ("modules", "lessons", "hours"):
        assert f'data-field="{field}"' in page

    assert page.count('data-mode="auto"') == 3
    assert page.count('data-mode="custom"') == 3
    assert "How course size is decided" in page


def test_script_asks_the_server_for_the_size():
    assert "/api/size" in script()
