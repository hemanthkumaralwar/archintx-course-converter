"""Tests for converter/chunking.py."""

import pytest

from converter.chunking import Section, split_long_text, split_sections
from converter.extractors import Block, text_to_blocks
from tests.sample_course import SAMPLE_LESSONS


def letters(texts):
    """All characters except whitespace, in order: what "no text lost" compares."""
    return "".join("".join(text.split()) for text in texts)


def assert_no_text_lost(blocks, sections):
    assert letters(section.text for section in sections) == letters(block.text for block in blocks)


# A realistic document built from the team's sample: module and lesson titles as
# headings, lesson explanations and code examples as paragraphs.
def sample_document_blocks():
    blocks = [Block("JavaScript Fundamentals", 1)]
    for lesson in SAMPLE_LESSONS[:6]:
        blocks.append(Block(lesson["title"], 2))
        blocks.append(Block(" ".join(lesson["lessonExplanation"][0]["points"])))
        blocks += [Block(example["code"]) for example in lesson["example"]]
    return blocks


# ---------------------------------------------------------------------------
# Headings
# ---------------------------------------------------------------------------


def test_heading_paths():
    blocks = [
        Block("Intro text"),
        Block("Variables", 1),
        Block("Use const."),
        Block("Scope", 2),
        Block("Blocks."),
        Block("Loops", 1),
        Block("for and while."),
    ]

    assert split_sections(blocks) == [
        Section("s1", (), "Intro text"),
        Section("s2", ("Variables",), "Variables\n\nUse const."),
        Section("s3", ("Variables", "Scope"), "Scope\n\nBlocks."),
        Section("s4", ("Loops",), "Loops\n\nfor and while."),
    ]


def test_headings_in_a_row_open_one_section():
    blocks = [Block("Course", 1), Block("Part 1", 2), Block("Lesson A", 3), Block("Text.")]

    assert split_sections(blocks) == [
        Section("s1", ("Course", "Part 1", "Lesson A"), "Course\n\nPart 1\n\nLesson A\n\nText.")
    ]


def test_skipped_heading_level_and_return_to_top_level():
    blocks = [Block("A", 1), Block("a"), Block("C", 3), Block("c"), Block("B", 1), Block("b")]

    assert [section.heading_path for section in split_sections(blocks)] == [
        ("A",),
        ("A", "C"),
        ("B",),
    ]


def test_document_of_only_headings():
    assert split_sections([Block("Title", 1), Block("Subtitle", 2)]) == [
        Section("s1", ("Title", "Subtitle"), "Title\n\nSubtitle")
    ]


def test_no_blocks_gives_no_sections():
    assert split_sections([]) == []


# ---------------------------------------------------------------------------
# Size limit
# ---------------------------------------------------------------------------


def test_small_paragraphs_are_packed_together_up_to_the_limit():
    blocks = [Block("Topic", 1)] + [Block("x" * 10) for _ in range(4)]

    sections = split_sections(blocks, max_chars=30)

    ten = "x" * 10
    assert sections == [
        Section("s1", ("Topic",), f"Topic\n\n{ten}\n\n{ten}"),  # 29 characters
        Section("s2", ("Topic",), f"{ten}\n\n{ten}"),
    ]


def test_packing_is_exact_at_the_limit():
    # "aaaa" + "\n\n" + "bbbb" is exactly 10 characters.
    assert [s.text for s in split_sections([Block("aaaa"), Block("bbbb")], max_chars=10)] == [
        "aaaa\n\nbbbb"
    ]
    assert [s.text for s in split_sections([Block("aaaa"), Block("bbbb")], max_chars=9)] == [
        "aaaa",
        "bbbb",
    ]


def test_long_paragraph_splits_at_line_break_and_keeps_indentation():
    code = "function f() {\n    return 1;\n}\n" * 3

    assert split_long_text(code, max_chars=20) == [
        "function f() {",
        "    return 1;\n}",
        "function f() {",
        "    return 1;\n}",
        "function f() {",
        "    return 1;\n}\n",
    ]


def test_long_paragraph_splits_after_a_sentence():
    text = "First sentence is here. Second sentence is longer than the rest."

    assert split_long_text(text, max_chars=30) == [
        "First sentence is here.",
        "Second sentence is longer than",
        "the rest.",
    ]


def test_long_paragraph_splits_at_a_space():
    assert split_long_text("aaaa bbbb cccc", max_chars=9) == ["aaaa bbbb", "cccc"]


def test_long_word_is_cut_hard():
    assert split_long_text("x" * 25, max_chars=10) == ["x" * 10, "x" * 10, "x" * 5]


def test_split_point_too_early_is_not_used():
    # The only space is at index 1, far below half the limit, so it is a hard cut.
    assert split_long_text("a " + "b" * 18, max_chars=10) == ["a " + "b" * 8, "b" * 10]


def test_short_text_is_one_piece_and_blank_text_none():
    assert split_long_text("short", max_chars=10) == ["short"]
    assert split_long_text("   ", max_chars=10) == []


@pytest.mark.parametrize("max_chars", [0, -5])
def test_invalid_limit(max_chars):
    with pytest.raises(ValueError, match="at least 1"):
        split_sections([Block("x")], max_chars=max_chars)


# ---------------------------------------------------------------------------
# Whole-document guarantees
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("max_chars", [1, 7, 40, 200, 3000])
def test_no_text_lost_and_no_section_too_long(max_chars):
    blocks = sample_document_blocks()

    sections = split_sections(blocks, max_chars=max_chars)

    assert_no_text_lost(blocks, sections)
    assert all(len(section.text) <= max_chars for section in sections)
    assert all(section.text.strip() for section in sections)


def test_ids_are_stable_for_the_same_input():
    blocks = sample_document_blocks()

    assert split_sections(blocks, 500) == split_sections(list(blocks), 500)


def test_works_on_extracted_text():
    text = "# Variables\n\nUse const.\n\n## Scope\n\nBlocks create scope.\n\nlet x = 1;\nx += 1;"
    blocks = text_to_blocks(text)

    sections = split_sections(blocks)

    assert [section.heading_path for section in sections] == [
        ("Variables",),
        ("Variables", "Scope"),
    ]
    assert sections[1].text == "Scope\n\nBlocks create scope.\n\nlet x = 1;\nx += 1;"
    assert_no_text_lost(blocks, sections)
