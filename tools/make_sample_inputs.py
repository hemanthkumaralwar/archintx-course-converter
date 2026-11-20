"""
make_sample_inputs.py

WHAT: Builds samples/inputs/python-basics.docx and python-basics.pdf from
      samples/inputs/python-basics.txt, so the same document exists in all
      three supported formats.

WHY:  The demo and the end-to-end runs need one document per format. Building
      the .docx and .pdf from the .txt keeps the three identical in content
      and lets anyone rebuild them after editing the text.

FORMATS:
    .docx  "#" and "##" lines become Heading 1 and Heading 2; code lines keep
           their indentation.
    .pdf   Plain text pages (Helvetica 10 pt). Headings are ordinary lines,
           like most PDFs exported from slides or simple editors.

USAGE:
    python tools/make_sample_inputs.py
"""

import re
import textwrap
from pathlib import Path

import docx
from pypdf import PdfWriter
from pypdf.generic import DecodedStreamObject, DictionaryObject, NameObject

INPUTS = Path(__file__).resolve().parent.parent / "samples" / "inputs"
SOURCE = INPUTS / "python-basics.txt"

HEADING = re.compile(r"^(#{1,2})\s+(.*)$")

# PDF page layout: A4-ish US Letter, 10 pt text, 72 pt margins.
PAGE_WIDTH, PAGE_HEIGHT = 612, 792
MARGIN, LINE_HEIGHT, FONT_SIZE = 72, 13, 10
CHARACTERS_PER_LINE = 95
LINES_PER_PAGE = (PAGE_HEIGHT - 2 * MARGIN) // LINE_HEIGHT


def build_docx(lines, target):
    document = docx.Document()

    for line in lines:
        heading = HEADING.match(line)
        if heading:
            document.add_heading(heading.group(2), level=len(heading.group(1)))
        elif line.strip():
            document.add_paragraph(line)

    document.save(target)


def pdf_lines(lines):
    """Wrap long prose lines; keep code lines (indented or short) as they are."""
    wrapped = []
    for line in lines:
        text = HEADING.sub(r"\2", line)
        if len(text) <= CHARACTERS_PER_LINE:
            wrapped.append(text)
        else:
            wrapped += textwrap.wrap(text, CHARACTERS_PER_LINE)
    return wrapped


def pdf_escape(text):
    return text.replace("\\", "\\\\").replace("(", "\\(").replace(")", "\\)")


def build_pdf(lines, target):
    writer = PdfWriter()
    font = DictionaryObject(
        {
            NameObject("/Type"): NameObject("/Font"),
            NameObject("/Subtype"): NameObject("/Type1"),
            NameObject("/BaseFont"): NameObject("/Helvetica"),
        }
    )
    page_lines = pdf_lines(lines)

    for start in range(0, len(page_lines), LINES_PER_PAGE):
        page = writer.add_blank_page(PAGE_WIDTH, PAGE_HEIGHT)
        shown = " ".join(
            f"({pdf_escape(line)}) Tj 0 -{LINE_HEIGHT} Td"
            for line in page_lines[start : start + LINES_PER_PAGE]
        )
        stream = DecodedStreamObject()
        top = PAGE_HEIGHT - MARGIN
        stream.set_data(f"BT /F1 {FONT_SIZE} Tf {MARGIN} {top} Td {shown} ET".encode("latin-1"))
        # pypdf has no public way to add a stream object; add_page uses _add_object too.
        page[NameObject("/Contents")] = writer._add_object(stream)
        page[NameObject("/Resources")] = DictionaryObject(
            {NameObject("/Font"): DictionaryObject({NameObject("/F1"): font})}
        )

    with target.open("wb") as file:
        writer.write(file)


def main():
    lines = SOURCE.read_text(encoding="utf-8").splitlines()
    build_docx(lines, SOURCE.with_suffix(".docx"))
    build_pdf(lines, SOURCE.with_suffix(".pdf"))
    print(f"Wrote {SOURCE.with_suffix('.docx').name} and {SOURCE.with_suffix('.pdf').name}")


if __name__ == "__main__":
    main()
