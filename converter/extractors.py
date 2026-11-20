"""
extractors.py

WHAT: Reads a .txt, .docx or .pdf file and returns its text as ordered blocks:
      headings (with a level) and paragraphs.

WHY:  Uploaded documents are untrusted. Every limit is checked before or while
      parsing, so a huge, disguised or malicious file is rejected with a clear
      message instead of exhausting memory or crashing the converter.

OUT OF SCOPE: OCR of scanned PDFs, .doc/.rtf/.odt, images, text boxes,
      headers, footers and footnotes. Tables become one text line per row.
"""

import codecs
import logging
import re
import zipfile
from dataclasses import dataclass
from io import BytesIO
from pathlib import Path

import docx
from docx.table import Table
from pypdf import PasswordType, PdfReader

from .exceptions import ExtractionError

logger = logging.getLogger(__name__)

MEGABYTE = 1024 * 1024

PDF_SIGNATURE = b"%PDF-"
ZIP_SIGNATURE = b"PK\x03\x04"
UTF16_BOMS = (codecs.BOM_UTF16_LE, codecs.BOM_UTF16_BE)
DOCX_MAIN_PART = "word/document.xml"

# A whole paragraph made of one Markdown-style heading line, such as "## Loops".
# Only a one-line paragraph counts, so a "# comment" line inside code is not
# mistaken for a heading.
MARKDOWN_HEADING = re.compile(r"^(#{1,6})\s+(\S.*)$")

# Word heading styles: "Heading 1" to "Heading 9". "Title" is treated as level 1.
WORD_HEADING_STYLE = re.compile(r"^Heading ([1-9])$")


@dataclass(frozen=True)
class Block:
    """One piece of a document: a heading (heading_level 1 or more) or a paragraph (0)."""

    text: str
    heading_level: int = 0


@dataclass(frozen=True)
class ExtractionLimits:
    """
    WHAT: Size limits for one input document.

    WHY:  The defaults (PLAN.md §6.4 Step 4) keep one upload small enough to
          read in memory and to convert within the free Gemini quota. Tests
          pass smaller limits instead of building huge files.
    """

    max_file_bytes: int = 10 * MEGABYTE
    max_pdf_pages: int = 200
    # Total unpacked size of a .docx. A .docx is a zip archive, so a small file
    # can unpack to gigabytes (a "zip bomb"); this is checked before parsing.
    max_docx_unzipped_bytes: int = 50 * MEGABYTE
    max_characters: int = 500_000


DEFAULT_LIMITS = ExtractionLimits()


def extract_blocks(path, limits=DEFAULT_LIMITS):
    """
    WHAT: Read one document and return its text as a list of Blocks, in order.

    RAISES:
        ExtractionError: if the file is missing, empty, too large, of an
                         unsupported type, disguised as another type,
                         password-protected, unreadable, or has no text.
    """
    path = Path(path)
    name = path.name
    reader = READERS.get(path.suffix.lower())

    if reader is None:
        raise ExtractionError(f"'{name}' is not a supported file type. Use .txt, .docx or .pdf.")

    data = _read_bytes(path, limits)
    blocks = reader(data, name, limits)

    if not blocks:
        hint = SCANNED_PDF_HINT if path.suffix.lower() == ".pdf" else ""
        raise ExtractionError(f"'{name}' contains no text.{hint}")

    characters = sum(len(block.text) for block in blocks)

    if characters > limits.max_characters:
        raise ExtractionError(
            f"'{name}' has {characters:,} characters of text; the limit is "
            f"{limits.max_characters:,}. Split it into smaller documents."
        )

    logger.info(
        "Read %s: %d bytes, %d blocks, %d characters", name, len(data), len(blocks), characters
    )
    return blocks


def _read_bytes(path, limits):
    """Return the file's bytes after checking that it exists and is within the size limit."""
    name = path.name

    if not path.is_file():
        raise ExtractionError(f"'{name}' was not found.")

    size = path.stat().st_size

    if size == 0:
        raise ExtractionError(f"'{name}' is empty.")

    if size > limits.max_file_bytes:
        raise ExtractionError(
            f"'{name}' is {size / MEGABYTE:.1f} MB; the limit is "
            f"{limits.max_file_bytes / MEGABYTE:g} MB."
        )

    return path.read_bytes()


def _wrong_content(name, expected):
    return ExtractionError(
        f"'{name}' does not contain {expected}. Check the file and its extension."
    )


# ---------------------------------------------------------------------------
# Plain text
# ---------------------------------------------------------------------------


def _read_txt(data, name, limits):
    return text_to_blocks(_decode_text(data, name))


def _decode_text(data, name):
    """
    WHAT: Decode a text file.

    HOW:  UTF-16 when it starts with a UTF-16 byte-order mark (Windows Notepad's
          "Unicode"); otherwise UTF-8 (with or without a byte-order mark), then
          Windows-1252, the usual encoding of older Windows text files.
    """
    if data.startswith(UTF16_BOMS):
        encodings = ("utf-16",)
    elif data.startswith((PDF_SIGNATURE, ZIP_SIGNATURE)) or b"\x00" in data:
        # NUL bytes never appear in UTF-8 or Windows-1252 text, only in binary files.
        raise _wrong_content(name, "plain text")
    else:
        encodings = ("utf-8-sig", "cp1252")

    for encoding in encodings:
        try:
            return data.decode(encoding)
        except UnicodeDecodeError:
            continue

    raise ExtractionError(
        f"'{name}' is not in a known text encoding. Save it as UTF-8 and try again."
    )


def text_to_blocks(text):
    """
    WHAT: Split plain text into paragraphs at blank lines.

    WHY:  Line breaks inside a paragraph are kept, because they matter in code
          examples. A paragraph that is a single Markdown heading line becomes
          a heading block.
    """
    blocks = []

    for paragraph in re.split(r"\n\s*\n", text.replace("\r\n", "\n").replace("\r", "\n")):
        paragraph = paragraph.strip("\n").rstrip()

        if not paragraph.strip():
            continue

        heading = MARKDOWN_HEADING.match(paragraph.strip())

        if heading and "\n" not in paragraph:
            blocks.append(Block(heading.group(2).strip(), len(heading.group(1))))
        else:
            blocks.append(Block(paragraph))

    return blocks


# ---------------------------------------------------------------------------
# Word (.docx)
# ---------------------------------------------------------------------------


def _read_docx(data, name, limits):
    _check_docx_archive(data, name, limits)

    try:
        document = docx.Document(BytesIO(data))
        items = list(document.iter_inner_content())
    except Exception as exc:
        # Trust boundary: a damaged file can make the parser raise almost any
        # exception type. The user gets one clear message; the cause is chained.
        raise ExtractionError(f"'{name}' could not be read as a Word document.") from exc

    return [block for item in items for block in _docx_item_blocks(item)]


def _check_docx_archive(data, name, limits):
    """Reject files that are not a Word archive, or that unpack beyond the size limit."""
    if not data.startswith(ZIP_SIGNATURE):
        raise _wrong_content(name, "a Word document")

    try:
        with zipfile.ZipFile(BytesIO(data)) as archive:
            entries = archive.infolist()
    except zipfile.BadZipFile as exc:
        raise ExtractionError(f"'{name}' could not be read as a Word document.") from exc

    if DOCX_MAIN_PART not in {entry.filename for entry in entries}:
        raise _wrong_content(name, "a Word document")

    # zipfile never unpacks more than an entry's declared size, so the sum of
    # declared sizes is a safe upper bound on what parsing will unpack.
    unzipped = sum(entry.file_size for entry in entries)

    if unzipped > limits.max_docx_unzipped_bytes:
        raise ExtractionError(
            f"'{name}' unpacks to {unzipped / MEGABYTE:.0f} MB; the limit is "
            f"{limits.max_docx_unzipped_bytes / MEGABYTE:g} MB."
        )


def _docx_item_blocks(item):
    """Return the blocks for one top-level paragraph or table of a Word document."""
    if isinstance(item, Table):
        return [Block(row) for row in _table_rows(item)]

    text = item.text.strip()

    if not text:
        return []

    style = item.style.name if item.style is not None else ""
    return [Block(text, _word_heading_level(style))]


def _table_rows(table):
    """Return each table row as "cell | cell | cell", skipping empty rows."""
    rows = []

    for row in table.rows:
        cells = []
        for cell in row.cells:
            text = " ".join(cell.text.split())
            # A merged cell is returned once per column it spans; keep it once.
            if text and (not cells or cells[-1] != text):
                cells.append(text)

        if cells:
            rows.append(" | ".join(cells))

    return rows


def _word_heading_level(style_name):
    if style_name == "Title":
        return 1

    match = WORD_HEADING_STYLE.match(style_name)
    return int(match.group(1)) if match else 0


# ---------------------------------------------------------------------------
# PDF
# ---------------------------------------------------------------------------


def _read_pdf(data, name, limits):
    if not data.startswith(PDF_SIGNATURE):
        raise _wrong_content(name, "a PDF")

    reader = _open_pdf(data, name)
    page_count = len(reader.pages)

    if page_count > limits.max_pdf_pages:
        raise ExtractionError(
            f"'{name}' has {page_count} pages; the limit is {limits.max_pdf_pages}."
        )

    logger.info("Reading %s: %d pages", name, page_count)
    return [block for text in _pdf_page_texts(reader, name) for block in text_to_blocks(text)]


def _open_pdf(data, name):
    """Open a PDF, unlocking it only when it opens without a password."""
    try:
        reader = PdfReader(BytesIO(data))
        locked = reader.is_encrypted and reader.decrypt("") == PasswordType.NOT_DECRYPTED
    except Exception as exc:
        # Trust boundary: see _read_docx.
        raise ExtractionError(f"'{name}' could not be read as a PDF.") from exc

    if locked:
        raise ExtractionError(
            f"'{name}' is password-protected. Remove the password and upload it again."
        )

    return reader


def _pdf_page_texts(reader, name):
    try:
        return [page.extract_text() or "" for page in reader.pages]
    except Exception as exc:
        # Trust boundary: see _read_docx.
        raise ExtractionError(f"'{name}' could not be read as a PDF.") from exc


# One reader per supported extension. Adding a format means adding one
# function with the signature (data, name, limits) -> list[Block] here.
READERS = {
    ".txt": _read_txt,
    ".docx": _read_docx,
    ".pdf": _read_pdf,
}

# A PDF with pages but no text is almost always a scan (pictures of pages).
SCANNED_PDF_HINT = " It may be a scanned document; scanned PDFs are not supported."
