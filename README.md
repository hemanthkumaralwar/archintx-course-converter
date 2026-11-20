# Archintx Course Converter

Converts course material in `.txt`, `.docx` and `.pdf` files into structured course JSON
in the format of [`samples/javascript-beginner.json`](samples/javascript-beginner.json),
using Google Gemini (free tier) or, optionally, OpenAI.

> **Status:** work in progress. The document converter is being built; see [PLAN.md](PLAN.md).
> The original title-based course generator still works (below).

## Project layout

| Path | Contents |
|---|---|
| `converter/` | Python package: pipeline, prompts, content checks, validation, retries |
| `converter/providers/` | LLM providers (`gemini.py` now, `openai.py` planned) |
| `app/` | Web app (planned) |
| `schema/course_schema.json` | JSON Schema every output must match |
| `samples/` | Reference output from the team, and sample input files |
| `tools/` | `generate_schema.py` and `validate_json.py` |
| `tests/` | Tests (planned) |
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

## Checks (development)

```bash
ruff check .                 # lint (PEP 8, unused code, likely bugs, complexity ≤ 10)
ruff format --check .        # formatting
pytest --cov                 # tests with coverage
pip-audit -r requirements.txt -r requirements-dev.txt   # known vulnerabilities
```

## Run (from the project root)

Original generator (course from a title, no input document):

```bash
python -m converter.generate --title "AI Engineering fundamentals" --difficulty beginner --duration 31
```

Validate a course file against the schema:

```bash
python tools/validate_json.py samples/javascript-beginner.json schema/course_schema.json
```

Rebuild the schema from the sample:

```bash
python tools/generate_schema.py samples/javascript-beginner.json -o schema/course_schema.json
```
