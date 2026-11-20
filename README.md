# Archintx Course Converter

Converts course material in `.txt`, `.docx` and `.pdf` files into structured course JSON
in the format of the team's reference course, [`samples/javascript-beginner.json`](samples/javascript-beginner.json):
modules, lessons, explanations, code examples, diagrams, quizzes and exercises.

It runs on your own computer, from the command line or a local web page. The only part
that goes online is the call to the LLM API: Google Gemini (free tier, default) or,
optionally, OpenAI.

> **Status:** the converter and the web page work, with 452 passing tests (96 % coverage)
> and real conversions of all three file types in [`docs/TEST_RESULTS.md`](docs/TEST_RESULTS.md).
> Open work is listed in [PLAN.md](PLAN.md) (Step 15Q and follow-ups F1–F3).

## Quick start (10–20 minutes, mostly installing packages)

**You need:** Python 3.12 or newer, internet access for the LLM API, and a free Gemini API key
from <https://aistudio.google.com/apikey>.

```bash
git clone https://github.com/hemanthkumaralwar/archintx-course-converter.git
cd archintx-course-converter
python -m venv venv
venv\Scripts\activate
pip install -r requirements-dev.txt
copy .env.example .env
```

On macOS or Linux, use `source venv/bin/activate` and `cp .env.example .env` instead.
`requirements-dev.txt` installs everything, including the test tools; to run the converter
only, `pip install -r requirements.txt` is enough.

Open `.env` and set `GEMINI_API_KEY=` to your key. Then:

```bash
pytest -q
```

```bash
python -m converter.cli samples/inputs/python-basics.pdf --modules 2 --lessons 3 -o course.json
```

```bash
python tools/validate_json.py course.json schema/course_schema.json
```

The tests need no network. The conversion takes about 2 minutes (about 10 Gemini calls)
and ends with `VALID`. If it stops with "503 high demand" (Gemini is busy), run the same
command again: the finished parts are kept and it continues.

## Documentation

| Document | What it covers |
|---|---|
| [docs/TECHNICAL.md](docs/TECHNICAL.md) | Architecture, every module, the conversion steps, output rules, prompt design, security, configuration, limits |
| [docs/TEST_RESULTS.md](docs/TEST_RESULTS.md) | Real Gemini runs (outlines, a reviewed lesson, three full conversions) and the test-suite results |
| [docs/DEMO.md](docs/DEMO.md) | A script for a 15-minute live demonstration on your own computer |
| [docs/SPIKE_GEMINI.md](docs/SPIKE_GEMINI.md) | The first Gemini free-tier measurements |
| [docs/examples/](docs/examples/) | Finished courses converted from the three sample files |
| [PLAN.md](PLAN.md) | The build plan, step by step, with what was done and decided at each step |
| [docs/LEGACY_GENERATOR.md](docs/LEGACY_GENERATOR.md) | The original title-based generator this project grew from |

## Convert a document

```bash
python -m converter.cli INPUT [--modules N --lessons M] [--provider gemini|openai] [-o FILE] [--output-dir DIR]
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

### Choosing the LLM: Gemini or OpenAI

Gemini is the default and works on Google's free tier. To use OpenAI instead,
change `.env` only (no code change):

```env
LLM_PROVIDER=openai
OPENAI_API_KEY=your_openai_key
OPENAI_MODEL=gpt-4o-mini     # any current model that supports JSON-schema output
```

Set `LLM_PROVIDER=gemini` to switch back. OpenAI is a paid API.

**Privacy:** the document's text is sent to the LLM API. On Gemini's free tier, Google may
use what you send to improve its products, so do not convert confidential documents there.

## Web page

Set `DEMO_ACCESS_CODE` in `.env` to a code of your choice (conversions stay switched off
without it), then start the local server:

```bash
uvicorn app.main:create_app --factory
```

Open <http://localhost:8000>, choose a file (or press **Use the sample document**), pick the
size, enter the access code, and press **Convert**. The page shows progress, a preview of the
course JSON and a **Download JSON** button. It works on phone-sized screens.

### API

| Endpoint | Purpose |
|---|---|
| `POST /api/convert` | Form upload: `file` (.txt, .docx, .pdf, up to 10 MB), optional `modules` + `lessons`, optional `provider`. Returns `{"jobId": ...}` (202). |
| `GET /api/jobs/{jobId}` | `state` (queued, running, done, failed), `done` / `total` pieces, current `label`, `error` |
| `GET /api/jobs/{jobId}/download` | The finished course JSON |
| `GET /healthz` | `{"status": "ok"}` (no access code needed) |

Every `/api` request needs the header `X-Access-Code`. A visitor may send their own key
in `X-API-Key`; it is used for that job only and never logged or stored. One conversion
runs at a time (a second one gets 429). Finished courses can be downloaded for one hour;
jobs are kept in memory, so a server restart forgets them. Documents are read in a
separate process that is stopped after 60 seconds.

## Development checks

```bash
ruff check .                 # lint (PEP 8, unused code, likely bugs, complexity ≤ 10)
ruff format --check .        # formatting
pytest --cov                 # tests with coverage
pip-audit -r requirements.txt -r requirements-dev.txt   # known vulnerabilities
```

## Project layout

| Path | Contents |
|---|---|
| `converter/` | Python package: reading files, sections, outline, writing lessons, checks, retries, CLI |
| `converter/providers/` | LLM providers: `gemini.py` (default, free tier) and `openai.py` (optional, paid) |
| `app/` | Web app: API (`main.py`), background jobs, upload page (`static/`) |
| `schema/course_schema.json` | JSON Schema every output must match |
| `samples/` | The team's reference course, and sample input files (`samples/inputs/`) |
| `tools/` | `validate_json.py`, `generate_schema.py`, `make_sample_inputs.py` |
| `tests/` | pytest tests; `tests/test_<module>.py` for each module |
| `docs/` | Documentation (see above) |
| `output/` | Work in progress (git-ignored) |

## Tools

Validate any course file against the schema:

```bash
python tools/validate_json.py samples/javascript-beginner.json schema/course_schema.json
```

Rebuild the schema from the sample:

```bash
python tools/generate_schema.py samples/javascript-beginner.json -o schema/course_schema.json
```

Rebuild the sample `.docx` and `.pdf` from `samples/inputs/python-basics.txt`:

```bash
python tools/make_sample_inputs.py
```

## Original generator (course from a title, no input document)

```bash
python -m converter.generate --title "AI Engineering fundamentals" --difficulty beginner --duration 31
```
