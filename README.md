# Archintx Course Converter

Converts course material in `.txt`, `.docx` and `.pdf` files into structured course JSON
in the format of [`samples/javascript-beginner.json`](samples/javascript-beginner.json),
using Google Gemini (free tier) or, optionally, OpenAI.

> **Status:** the command-line converter works; the web app is planned. See [PLAN.md](PLAN.md).
> The original title-based course generator also still works (below).

## Project layout

| Path | Contents |
|---|---|
| `converter/` | Python package: pipeline, prompts, content checks, validation, retries |
| `converter/providers/` | LLM providers: `gemini.py` (default, free tier) and `openai.py` (optional, paid) |
| `app/` | Web app (planned) |
| `schema/course_schema.json` | JSON Schema every output must match |
| `samples/` | Reference output from the team, and sample input files |
| `tools/` | `generate_schema.py` and `validate_json.py` |
| `tests/` | pytest tests; `tests/test_<module>.py` for each `converter/<module>.py` |
| `docs/` | Documentation. `LEGACY_GENERATOR.md` describes the original generator |
| `output/` | Results (git-ignored) |

## Setup

```bash
python -m venv venv
venv\Scripts\activate        # Windows
source venv/bin/activate     # macOS / Linux
pip install -r requirements.txt
pip install -r requirements-dev.txt   # tests, linter, security audit (development only)
cp .env.example .env         # then put your Gemini key in .env
```

### Choosing the LLM: Gemini or OpenAI

Gemini is the default and works on Google's free tier. To use OpenAI instead,
change `.env` only (no code change):

```env
LLM_PROVIDER=openai
OPENAI_API_KEY=your_openai_key
OPENAI_MODEL=gpt-4o-mini     # any current model that supports JSON-schema output
```

Set `LLM_PROVIDER=gemini` to switch back. OpenAI is a paid API. Note that on
Gemini's free tier Google may use what you send to improve its products, so
do not upload confidential documents there.

## Checks (development)

```bash
ruff check .                 # lint (PEP 8, unused code, likely bugs, complexity ≤ 10)
ruff format --check .        # formatting
pytest --cov                 # tests with coverage
pip-audit -r requirements.txt -r requirements-dev.txt   # known vulnerabilities
```

## Convert a document (from the project root)

```bash
python -m converter.cli samples/inputs/python-basics.pdf --modules 2 --lessons 3 -o course.json
```

| Option | Meaning |
|---|---|
| `INPUT` | A `.txt`, `.docx` or `.pdf` file (up to 10 MB, 200 pages; scanned PDFs are not supported) |
| `--modules N --lessons M` | Course size. Leave both out to size the course from the document's length (one lesson per ~3,000 characters, up to 8 x 8) |
| `--provider gemini\|openai` | Overrides `LLM_PROVIDER` in `.env` |
| `-o FILE` | Also save the finished course JSON to `FILE` |
| `--output-dir DIR` | Where work in progress is kept (default `output/`) |

Progress is shown as each piece is saved, for example `[4/10] Lesson 1.2: Numbers and Arithmetic (saved)`.
Work is kept in `output/<file name>-<file hash>/`, so if a run stops (Ctrl+C, network
error, daily quota), running the same command again continues from the next lesson.
An edited file gets a new folder and starts fresh.

Exit codes: `0` done, `1` an expected error (one-line message), `2` wrong arguments,
`130` stopped with Ctrl+C.

A 2 x 3 course takes about 10 API calls; the largest automatic size (8 x 8) about 74.

## Original generator (course from a title, no input document)

```bash
python -m converter.generate --title "AI Engineering fundamentals" --difficulty beginner --duration 31
```

## Tools

Validate a course file against the schema:

```bash
python tools/validate_json.py samples/javascript-beginner.json schema/course_schema.json
```

Rebuild the schema from the sample:

```bash
python tools/generate_schema.py samples/javascript-beginner.json -o schema/course_schema.json
```
