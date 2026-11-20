"""
Tests for converter/extractors.py.

Every input file is built at test time (Word files with python-docx, PDFs with
pypdf, archives with zipfile), so no binary fixtures are committed.
"""

import logging
import zipfile
from io import BytesIO

import docx
import pytest
from pypdf import PdfWriter
from pypdf.generic import DecodedStreamObject, DictionaryObject, NameObject

from converter.exceptions import ExtractionError
from converter.extractors import Block, ExtractionLimits, extract_blocks, text_to_blocks

SMALL = ExtractionLimits(
    max_file_bytes=4000, max_pdf_pages=2, max_docx_unzipped_bytes=20_000, max_characters=500
)


# ---------------------------------------------------------------------------
# File builders
# ---------------------------------------------------------------------------


def write(tmp_path, name, data):
    path = tmp_path / name
    path.write_bytes(data)
    return path


def make_pdf(pages, user_password=None, owner_password=None):
    """Build a PDF with one text page per entry; None makes a page with no text (like a scan)."""
    writer = PdfWriter()
    font = DictionaryObject(
        {
            NameObject("/Type"): NameObject("/Font"),
            NameObject("/Subtype"): NameObject("/Type1"),
            NameObject("/BaseFont"): NameObject("/Helvetica"),
        }
    )

    for text in pages:
        page = writer.add_blank_page(612, 792)
        if text is None:
            continue
        shown = " ".join(f"({line}) Tj 0 -14 Td" for line in text.split("\n"))
        stream = DecodedStreamObject()
        stream.set_data(f"BT /F1 12 Tf 72 720 Td {shown} ET".encode("latin-1"))
        # pypdf has no public way to add a stream object; _add_object is what add_page uses.
        page[NameObject("/Contents")] = writer._add_object(stream)
        page[NameObject("/Resources")] = DictionaryObject(
            {NameObject("/Font"): DictionaryObject({NameObject("/F1"): font})}
        )

    if user_password is not None:
        writer.encrypt(user_password=user_password, owner_password=owner_password)

    output = BytesIO()
    writer.write(output)
    return output.getvalue()


def make_docx(build):
    """Build a .docx; `build` receives the python-docx Document to fill."""
    document = docx.Document()
    build(document)
    output = BytesIO()
    document.save(output)
    return output.getvalue()


def make_zip(entries):
    output = BytesIO()
    with zipfile.ZipFile(output, "w", compression=zipfile.ZIP_DEFLATED) as archive:
        for name, content in entries.items():
            archive.writestr(name, content)
    return output.getvalue()


def fill_course_document(document):
    document.add_paragraph("Intro to JavaScript", style="Title")
    document.add_heading("Variables", level=1)
    document.add_paragraph("Use const by default.")
    document.add_paragraph("")
    table = document.add_table(rows=2, cols=2)
    table.cell(0, 0).text, table.cell(0, 1).text = "Keyword", "Meaning"
    table.cell(1, 0).text, table.cell(1, 1).text = "let", "Can be reassigned"
    document.add_heading("Scope", level=2)
    document.add_paragraph("Blocks create scope.")


# ---------------------------------------------------------------------------
# Plain text
# ---------------------------------------------------------------------------


def test_text_paragraphs_and_markdown_heading(tmp_path):
    text = "# Variables\n\nUse const by default.\nUse let when it changes.\n\n\n## Scope\n\nBlocks."
    path = write(tmp_path, "notes.txt", text.encode("utf-8"))

    assert extract_blocks(path) == [
        Block("Variables", 1),
        Block("Use const by default.\nUse let when it changes."),
        Block("Scope", 2),
        Block("Blocks."),
    ]


def test_code_comment_inside_paragraph_is_not_a_heading():
    assert text_to_blocks("x = 1\n# add one\nx += 1") == [Block("x = 1\n# add one\nx += 1")]


def test_text_without_newline_and_with_windows_line_endings(tmp_path):
    assert extract_blocks(write(tmp_path, "a.txt", b"one line")) == [Block("one line")]
    assert extract_blocks(write(tmp_path, "b.txt", b"first\r\n\r\nsecond\r\n")) == [
        Block("first"),
        Block("second"),
    ]


@pytest.mark.parametrize(
    "data",
    [
        "﻿café".encode(),  # UTF-8 with byte-order mark
        "café".encode("cp1252"),  # older Windows text
        "café".encode("utf-16"),  # Windows Notepad "Unicode" (has a byte-order mark)
    ],
    ids=["utf8-bom", "cp1252", "utf16"],
)
def test_text_encodings(tmp_path, data):
    assert extract_blocks(write(tmp_path, "a.txt", data)) == [Block("café")]


def test_text_in_unknown_encoding_is_rejected(tmp_path):
    # 0x81 is undefined in both UTF-8 (as a start byte) and Windows-1252.
    with pytest.raises(ExtractionError, match="not in a known text encoding"):
        extract_blocks(write(tmp_path, "a.txt", b"bad \x81 byte"))


@pytest.mark.parametrize(
    "data", [b"%PDF-1.7 ...", b"PK\x03\x04...", b"text\x00binary"], ids=["pdf", "zip", "nul"]
)
def test_binary_file_named_txt_is_rejected(tmp_path, data):
    with pytest.raises(ExtractionError, match="does not contain plain text"):
        extract_blocks(write(tmp_path, "a.txt", data))


# ---------------------------------------------------------------------------
# Word
# ---------------------------------------------------------------------------


def test_docx_headings_paragraphs_and_table_in_order(tmp_path):
    path = write(tmp_path, "course.docx", make_docx(fill_course_document))

    assert extract_blocks(path) == [
        Block("Intro to JavaScript", 1),
        Block("Variables", 1),
        Block("Use const by default."),
        Block("Keyword | Meaning"),
        Block("let | Can be reassigned"),
        Block("Scope", 2),
        Block("Blocks create scope."),
    ]


def test_docx_merged_cell_is_kept_once(tmp_path):
    def build(document):
        table = document.add_table(rows=1, cols=3)
        table.cell(0, 0).merge(table.cell(0, 1)).text = "Wide"
        table.cell(0, 2).text = "Narrow"

    assert extract_blocks(write(tmp_path, "t.docx", make_docx(build))) == [Block("Wide | Narrow")]


def test_docx_with_only_empty_paragraphs_has_no_text(tmp_path):
    path = write(tmp_path, "blank.docx", make_docx(lambda document: document.add_paragraph("  ")))

    with pytest.raises(ExtractionError, match="contains no text.$"):
        extract_blocks(path)


@pytest.mark.parametrize(
    ("data", "message"),
    [
        (b"plain words", "does not contain a Word document"),
        (b"PK\x03\x04 not really a zip", "could not be read as a Word document"),
        (make_zip({"other.xml": "<x/>"}), "does not contain a Word document"),
        (
            make_zip({"word/document.xml": "<not-word/>", "[Content_Types].xml": "<x/>"}),
            "could not be read",
        ),
    ],
    ids=["not-zip", "broken-zip", "zip-without-word-part", "broken-word-part"],
)
def test_bad_docx_is_rejected(tmp_path, data, message):
    with pytest.raises(ExtractionError, match=message):
        extract_blocks(write(tmp_path, "a.docx", data))


def test_docx_zip_bomb_is_rejected_before_parsing(tmp_path):
    # 1 MB of zeros compresses to about 1 KB: small on disk, large when unpacked.
    bomb = make_zip({"word/document.xml": "<w/>", "word/media/fill.bin": b"\x00" * 1_000_000})
    path = write(tmp_path, "bomb.docx", bomb)

    with pytest.raises(ExtractionError, match="unpacks to 1 MB"):
        extract_blocks(path, SMALL)


# ---------------------------------------------------------------------------
# PDF
# ---------------------------------------------------------------------------


def test_pdf_two_pages(tmp_path):
    path = write(tmp_path, "a.pdf", make_pdf(["Variables\nUse const.", "Loops"]))

    assert extract_blocks(path) == [Block("Variables\nUse const."), Block("Loops")]


def test_pdf_with_owner_password_only_is_read(tmp_path):
    data = make_pdf(["Readable"], user_password="", owner_password="owner")

    assert extract_blocks(write(tmp_path, "a.pdf", data)) == [Block("Readable")]


def test_pdf_that_needs_a_password_is_rejected(tmp_path):
    data = make_pdf(["Secret"], user_password="open-me", owner_password="owner")

    with pytest.raises(ExtractionError, match="password-protected"):
        extract_blocks(write(tmp_path, "a.pdf", data))


def test_scanned_pdf_is_rejected(tmp_path):
    with pytest.raises(ExtractionError, match="may be a scanned document"):
        extract_blocks(write(tmp_path, "scan.pdf", make_pdf([None, None])))


def test_pdf_with_too_many_pages_is_rejected(tmp_path):
    with pytest.raises(ExtractionError, match="has 3 pages; the limit is 2"):
        extract_blocks(write(tmp_path, "long.pdf", make_pdf(["a", "b", "c"])), SMALL)


@pytest.mark.parametrize(
    ("data", "message"),
    [(b"PK\x03\x04", "does not contain a PDF"), (b"%PDF-1.7 broken", "could not be read as a PDF")],
    ids=["zip-named-pdf", "broken-pdf"],
)
def test_bad_pdf_is_rejected(tmp_path, data, message):
    with pytest.raises(ExtractionError, match=message):
        extract_blocks(write(tmp_path, "a.pdf", data))


def test_pdf_page_that_cannot_be_read_is_rejected(tmp_path, monkeypatch):
    def broken_extract(self):
        raise KeyError("/Font")

    monkeypatch.setattr("pypdf.PageObject.extract_text", broken_extract)

    with pytest.raises(ExtractionError, match="could not be read as a PDF"):
        extract_blocks(write(tmp_path, "a.pdf", make_pdf(["text"])))


# ---------------------------------------------------------------------------
# Rules for every file type
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("name", ["a.doc", "a.rtf", "a.md", "noextension"])
def test_unsupported_type_is_rejected(tmp_path, name):
    with pytest.raises(ExtractionError, match="not a supported file type"):
        extract_blocks(write(tmp_path, name, b"text"))


def test_extension_is_case_insensitive(tmp_path):
    assert extract_blocks(write(tmp_path, "NOTES.TXT", b"Hello")) == [Block("Hello")]


def test_missing_file(tmp_path):
    with pytest.raises(ExtractionError, match="'gone.txt' was not found"):
        extract_blocks(tmp_path / "gone.txt")


@pytest.mark.parametrize(
    ("data", "message"), [(b"", "is empty"), (b" \n\t\n ", "contains no text")]
)
def test_empty_or_blank_file(tmp_path, data, message):
    with pytest.raises(ExtractionError, match=message):
        extract_blocks(write(tmp_path, "a.txt", data))


def test_file_size_limit(tmp_path):
    assert extract_blocks(write(tmp_path, "ok.txt", b"x" * 400), SMALL)

    with pytest.raises(ExtractionError, match=r"'big.txt' is 0\.0 MB; the limit is .* MB"):
        extract_blocks(write(tmp_path, "big.txt", b"x" * 4001), SMALL)


def test_character_limit(tmp_path):
    assert extract_blocks(write(tmp_path, "ok.txt", b"x" * 500), SMALL)

    with pytest.raises(ExtractionError, match="has 501 characters of text; the limit is 500"):
        extract_blocks(write(tmp_path, "long.txt", b"x" * 501), SMALL)


def test_error_message_names_the_file_but_not_its_folder(tmp_path):
    with pytest.raises(ExtractionError) as error:
        extract_blocks(write(tmp_path, "a.pdf", b"%PDF-1.7 broken"))

    assert "'a.pdf'" in str(error.value)
    assert str(tmp_path) not in str(error.value)
    assert error.value.__cause__ is not None  # the library error is kept for debugging


def test_log_has_file_facts_but_not_its_text(tmp_path, caplog):
    path = write(tmp_path, "private.txt", b"Confidential salary table")

    with caplog.at_level(logging.INFO, logger="converter.extractors"):
        extract_blocks(path)

    assert "private.txt" in caplog.text
    assert "Confidential" not in caplog.text
