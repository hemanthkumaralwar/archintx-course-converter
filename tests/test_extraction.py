"""Tests for app/extraction.py: reading a document in a child process with a time limit."""

import pytest

from app.extraction import extract_with_time_limit
from converter.exceptions import ExtractionError
from converter.extractors import Block
from tests.fakes import crashing_reader, failing_reader, slow_reader


def test_reads_the_document_in_a_child_process(tmp_path):
    path = tmp_path / "notes.txt"
    path.write_text("# Loops\n\nUse for.", encoding="utf-8")

    assert extract_with_time_limit(path) == [Block("Loops", 1), Block("Use for.")]


def test_extraction_error_keeps_its_message(tmp_path):
    path = tmp_path / "empty.txt"
    path.write_bytes(b"")

    with pytest.raises(ExtractionError, match="'empty.txt' is empty."):
        extract_with_time_limit(path)


def test_too_slow_is_stopped(tmp_path):
    with pytest.raises(ExtractionError, match="took too long to read \\(more than 1 seconds\\)"):
        extract_with_time_limit(tmp_path / "slow.pdf", seconds=1, target=slow_reader)


def test_child_that_dies_is_reported(tmp_path):
    with pytest.raises(ExtractionError, match="'dead.pdf' could not be read."):
        extract_with_time_limit(tmp_path / "dead.pdf", seconds=30, target=crashing_reader)


def test_unexpected_error_in_the_child_gets_a_generic_message(tmp_path):
    with pytest.raises(ExtractionError, match="'odd.pdf' could not be read."):
        extract_with_time_limit(tmp_path / "odd.pdf", seconds=30, target=failing_reader)
