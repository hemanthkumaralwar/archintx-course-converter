"""Tests for converter/cli.py: arguments, exit codes and output, with FakeProvider."""

import shutil
import socket

import pytest

from converter import cli
from converter.exceptions import ConfigurationError
from converter.json_utils import load_json
from tests.fakes import FakeProvider
from tests.sample_course import SAMPLE_INPUT, conversion_answers


@pytest.fixture(autouse=True)
def no_network(monkeypatch):
    def refuse(*args, **kwargs):
        raise AssertionError("tests must not use the network")

    monkeypatch.setattr(socket.socket, "connect", refuse)


@pytest.fixture
def document(tmp_path):
    path = tmp_path / "python-basics.txt"
    shutil.copy(SAMPLE_INPUT, path)
    return path


@pytest.fixture
def fake_llm(monkeypatch):
    """Replace get_provider; records the settings it was called with."""
    seen = {}

    def install(provider):
        def get_provider(settings):
            seen["settings"] = settings
            return provider

        monkeypatch.setattr(cli, "get_provider", get_provider)
        return seen

    return install


def run(document, tmp_path, *extra):
    return cli.main(
        [
            str(document),
            "--modules",
            "2",
            "--lessons",
            "3",
            "--output-dir",
            str(tmp_path / "work"),
            *extra,
        ]
    )


def test_success_prints_progress_and_exits_0(document, tmp_path, fake_llm, capsys):
    fake_llm(FakeProvider(conversion_answers()))

    assert run(document, tmp_path) == 0

    out = capsys.readouterr().out
    assert "[1/10] Course outline (saved)" in out
    assert "[10/10] Lesson 2.3: Putting It Together (saved)" in out
    assert "Done. The course matches the schema:" in out


def test_output_option_saves_a_copy(document, tmp_path, fake_llm):
    fake_llm(FakeProvider(conversion_answers()))
    target = tmp_path / "course.json"

    assert run(document, tmp_path, "-o", str(target)) == 0
    assert load_json(target)["course"]["courseTitle"] == "Python Basics for Complete Beginners"


def test_provider_option_overrides_the_setting(document, tmp_path, fake_llm):
    seen = fake_llm(FakeProvider(conversion_answers()))

    assert run(document, tmp_path, "--provider", "openai") == 0
    assert seen["settings"].llm_provider == "openai"


def test_expected_error_exits_1_with_one_line(tmp_path, fake_llm, capsys):
    fake_llm(FakeProvider([]))

    assert run(tmp_path / "missing.pdf", tmp_path) == 1
    assert "ERROR: 'missing.pdf' was not found." in capsys.readouterr().err


def test_missing_api_key_exits_1(document, tmp_path, monkeypatch, capsys):
    def missing_key(settings):
        raise ConfigurationError("GEMINI_API_KEY is missing. Add it to your .env file.")

    monkeypatch.setattr(cli, "get_provider", missing_key)

    assert run(document, tmp_path) == 1
    assert "GEMINI_API_KEY is missing" in capsys.readouterr().err


@pytest.mark.parametrize(
    "argv",
    [
        [],
        ["a.txt", "--modules", "2"],
        ["a.txt", "--lessons", "3"],
        ["a.txt", "--modules", "two", "--lessons", "3"],
        ["a.txt", "--provider", "claude"],
    ],
    ids=["no-input", "modules-only", "lessons-only", "not-a-number", "unknown-provider"],
)
def test_bad_arguments_exit_2(argv):
    with pytest.raises(SystemExit) as stop:
        cli.main(argv)

    assert stop.value.code == 2


def test_ctrl_c_exits_130_and_keeps_work(document, tmp_path, fake_llm, capsys):
    fake_llm(FakeProvider([KeyboardInterrupt()]))

    assert run(document, tmp_path) == 130
    assert "run the same command again to continue" in capsys.readouterr().err


def test_automatic_size_when_no_size_is_given(document, fake_llm, monkeypatch):
    seen = {}

    def fake_convert(path, provider, options, progress):
        seen["size"] = options.size
        raise ConfigurationError("stop here")

    fake_llm(FakeProvider([]))
    monkeypatch.setattr(cli, "convert", fake_convert)

    assert cli.main([str(document)]) == 1
    assert seen["size"] is None
