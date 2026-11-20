"""
chunking.py

WHAT: Groups a document's blocks (from extractors.py) into numbered sections,
      each with its heading path and at most `max_chars` characters of text.

WHY:  The outline step lists sections by id, and each lesson is later written
      from only the sections it cites. Small, stable sections keep those
      prompts short and let every lesson point at exactly the text it uses.
"""

from dataclasses import dataclass

# About one printed page. Small enough that a lesson can cite only the parts it
# needs; large enough that a typical document section stays in one piece.
DEFAULT_MAX_SECTION_CHARS = 3000

# Where to split a paragraph that is too long, best first: a line break (keeps
# code lines whole), a sentence end, a space. A cut is only used if it keeps at
# least half the allowed length, so splitting does not leave tiny pieces.
SPLIT_POINTS = ("\n", ". ", " ")

PARAGRAPH_BREAK = "\n\n"


@dataclass(frozen=True)
class Section:
    """
    One numbered piece of a document.

    id:           "s1", "s2", ... in document order (the same input gives the same ids).
    heading_path: the headings above this text, outermost first; empty before the first heading.
    text:         the section's text, starting with its own heading lines.
    """

    id: str
    heading_path: tuple
    text: str


def split_sections(blocks, max_chars=DEFAULT_MAX_SECTION_CHARS):
    """
    WHAT: Turn ordered blocks into sections.

    HOW:  A new section starts at each heading that follows some text. Headings
          in a row (a title, then a chapter heading) open one section together.
          Paragraphs are packed into the section up to `max_chars`; the rest
          continues in further sections with the same heading path.

    RETURNS:
        A list of Sections. Joining their text gives back every character of
        the blocks, in order (only whitespace at split points may change).

    RAISES:
        ValueError: if max_chars is less than 1.
    """
    if max_chars < 1:
        raise ValueError(f"max_chars must be at least 1 (got {max_chars}).")

    sections = []

    for heading_path, texts in _group_by_heading(blocks):
        for text in _pack(texts, max_chars):
            sections.append(Section(f"s{len(sections) + 1}", heading_path, text))

    return sections


def _group_by_heading(blocks):
    """Return (heading_path, [block texts]) groups; each group starts at its headings."""
    groups = []
    path = []
    texts = []
    has_paragraph = False

    for block in blocks:
        if block.heading_level and has_paragraph:
            # `path` still belongs to the group being closed.
            groups.append((tuple(path), texts))
            texts, has_paragraph = [], False

        if block.heading_level:
            # A heading replaces any heading at its level or deeper.
            path = path[: block.heading_level - 1] + [block.text]
        else:
            has_paragraph = True

        texts.append(block.text)

    if texts:
        groups.append((tuple(path), texts))

    return groups


def _pack(texts, max_chars):
    """Join texts with paragraph breaks into chunks of at most max_chars."""
    chunks = []
    current = ""

    for piece in (piece for text in texts for piece in split_long_text(text, max_chars)):
        candidate = f"{current}{PARAGRAPH_BREAK}{piece}" if current else piece

        if len(candidate) <= max_chars:
            current = candidate
        else:
            chunks.append(current)
            current = piece

    if current:
        chunks.append(current)

    return chunks


def split_long_text(text, max_chars):
    """
    WHAT: Split one paragraph into pieces of at most max_chars.

    WHY:  Only trailing whitespace is removed at a cut, never the start of the
          next piece, so indentation in code survives.
    """
    pieces = []

    while len(text) > max_chars:
        cut = _cut_point(text, max_chars)
        piece = text[:cut].rstrip()

        if piece:
            pieces.append(piece)

        text = text[cut:]

    if text.strip():
        pieces.append(text)

    return pieces


def _cut_point(text, max_chars):
    """Return where to cut text so the first piece (without trailing spaces) fits max_chars."""
    # One extra character, so a split point sitting right at the limit is found.
    window = text[: max_chars + 1]

    for split_point in SPLIT_POINTS:
        index = window.rfind(split_point)

        if index >= max(1, max_chars // 2):
            # Cut after the split point; the caller's rstrip drops the space or
            # line break, so the first piece is never longer than max_chars.
            return index + len(split_point)

    return max_chars
