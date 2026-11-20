# PLAN.md — Archintx Course Converter

## 1. Project brief

| Field | Value |
|---|---|
| **Project** | Archintx Course Converter |
| **Product purpose** | Converts course material in `.txt`, `.docx` or `.pdf` files into structured course JSON that follows the format of `javascript-beginner.json` (course → modules → lessons, with quizzes, exercises, diagrams and other activities). An LLM reads the document and maps its content into that structure. |
| **Target users** | The Archintx content team and course authors who have material in documents and need it as JSON for the learning platform, without writing JSON by hand. |
| **Technology stack** | Python 3.12 · FastAPI (web API and upload page) · plain HTML/CSS/JS front end · `pypdf` (PDF text) · `python-docx` (Word text) · `jsonschema` (validation) · `google-genai` (Gemini, default) · `openai` (optional, switchable) · `pytest` (tests) · no database; files on disk. |
| **Deployment environment** | Local for development. Live demo on a free host: Render free web service (recommended) or Hugging Face Spaces. Code on GitHub. |
| **Current stage** | Existing codebase. An earlier Python prototype generates courses from a title using Gemini. It does not read documents yet. |
| **Task** | Build a converter that takes an uploaded `.txt`, `.docx` or `.pdf`, extracts its text, uses Gemini (or OpenAI) to turn it into JSON matching `javascript-beginner.json`, validates the result against a schema, and returns the JSON file. Provide a CLI and a web page. |
| **Constraints** | Budget ₹0: free-tier Gemini, free hosting, open-source libraries only. LLM provider must be switchable to OpenAI with a setting, without code changes. API keys stay in `.env` and never reach GitHub. Free-tier rate limits apply, so the converter must make few, small requests, retry on failure and resume after interruption. Final submission: source code, GitHub link, technical documentation, test results, live demo. |

---

## 2. What the old codebase does

The repository holds a working **course generator**, not a converter. You give it a
title, a difficulty and a duration in hours, and it asks Gemini to write a whole course
from scratch in the `javascript-beginner.json` format. It does not read any input
document.

### How it runs

```
python main.py --title "AI Engineering fundamentals" --difficulty beginner --duration 31
```

1. **Input** (`user_input.py`): reads title, difficulty and hours; works out the number of
   modules (hours ÷ (8 lessons × 30 min), rounded up, limited to 2–30).
2. **Schema** (`schema_utils.py`): loads `course_schema.json` and builds smaller schemas for
   each step (course details, module overview, single lesson) with fixed item counts.
3. **Plan** (`planner.py`): one Gemini call returns every module title and its 8 lesson titles.
   Saved to `output/<slug>/<slug>_plan.json`.
4. **Course details** (`planner.py`): one call for the course description and other top-level fields.
5. **Modules and lessons** (`module_writer.py`): one call per module overview and one per
   lesson. Each lesson is checked in code beyond the schema (objective has 4 numbered points,
   quiz answers are valid indexes, code reordering is consistent, card pairs match, Mermaid
   diagrams parse, etc.). Bad sections are repaired with a follow-up call.
6. **Save and resume** (`checkpoint.py`, `json_utils.py`): every piece is saved straight away
   with an atomic write. Rerunning the same command resumes from the next missing lesson.
7. **Final check** (`validation.py`): the whole file is validated against `course_schema.json`.

Gemini is called with `response_json_schema`, so it must answer in the right shape.
Failed attempts are retried up to 3 times with the errors fed back into the prompt (`retry.py`).

### File-by-file

File names below are from before the reorganisation. They now live in `converter/`
(`main.py` → `converter/generate.py`, `gemini_service.py` → `converter/providers/gemini.py`),
`tools/`, `schema/`, `samples/` and `docs/`; see section 5.

| File | Role | Reuse in the converter? |
|---|---|---|
| `main.py` | CLI entry point, exit codes | Rewrite (new arguments: input file) |
| `user_input.py` | Title/difficulty/duration input, module count, output paths | Partly (paths, slug); input logic replaced |
| `config.py` | Settings: counts per lesson, retries, model, API key | **Keep**, add provider settings |
| `pipeline.py` | Orchestrates plan → details → modules → final check | **Keep the shape**, add an "extract document" step first |
| `planner.py` | Outline and course-details calls | Adapt: outline comes *from the document* |
| `module_writer.py` | Lesson/overview calls, ~20 content checks, repair calls | **Keep** (most valuable file) |
| `prompts.py` | All prompt text | Adapt: prompts must say "use this source material" |
| `gemini_service.py` | Only file that talks to Gemini | Becomes one of two providers |
| `schema_utils.py` | Builds step schemas from `course_schema.json` | **Keep** |
| `validation.py`, `retry.py`, `exceptions.py`, `checkpoint.py`, `json_utils.py` | Helpers | **Keep** |
| `generate_schema.py` | Builds a JSON Schema from an example JSON | **Keep** (regenerate schema from the sample) |
| `validate_json.py` | Checks a JSON file against a schema | **Keep** (used in tests and docs) |
| `course_schema.json` | Schema made from the sample | **Keep** |
| `ReadME.md` | Docs for the old generator | Replace with new `README.md` |
| `requirements.txt` | Pinned packages | Update (add FastAPI, pypdf, python-docx, openai, pytest; remove stray `style`, `update`) |
| `.env` | Real Gemini key | Keep locally, never commit |
| `.env.example.env` | Key template (odd name) | Rename to `.env.example` |
| `.gitignore`, `.gitattributes` | Git settings | Keep, add `output/` |
| `venv/`, `__pycache__/` | Generated environment/cache | Safe to delete, recreated by setup |
| `output/` | Empty output folder | Keep |

### Things noticed in the old code and the sample

- The folder is **not a git repository** yet, so there is no history or undo.
- `javascript-beginner.json` says `totalDuration: "12 hours"`, but its modules add up to
  37 hours. The converter should compute the total from the modules.
- `useCaseCards` has 3 items in 61 lessons and 4 in 3 lessons. The config fixes it at 3; keep 3.
- Lesson durations in the sample are 20, 25 or 30 minutes; modules are 4 or 5 hours.
- README examples use `javascript_beginner.json` (underscore), but the file is `javascript-beginner.json`.
- `requirements.txt` contains `style` and `update`, which are not used and look like accidental installs.

---

## 3. Target output (from `javascript-beginner.json`)

```
course: courseId, courseTitle, courseDescription, level, totalDuration
  modules[8]: moduleId, title, description, duration,
              moduleExplanation[1]{topic, points[8]}
    lessons[8]: lessonId, title, objective, duration,
                lessonExplanation[1]{topic, points[8]},
                hooklines_title, hooklineimage{status, html, alt, prompt, style},
                hooklines[2]{text, image}, concepts[8],
                syntax{title, highlight{code}}, parts[8]{label, name, description},
                analogy{subject, comparison, mapping[5]{from, to}},
                example[5]{title, code, explanation},
                flowchart{title, type, code}            (Mermaid)
                interactiveExercise{title, instruction, starterCode, expectebehavior},
                quiz[10]{question, options[4], correctAnswer (index as string), explanation},
                codereordering{title, instruction, codelines[6], correctOrder[6]},
                dragandropp{title, instruction, items[6]{id, content, correctCategory}, correctpairs[2]},
                cardmatching{title, instruction, cards[12]{id, content}, matches[6]{card1Id, card2Id}},
                bugHunt{title, instruction, buggyCode, bug, fixedCode, hint},
                miniChallenge{title, scenario, prompt, starterCode, hints[2], expectedOutput, difficulty},
                useCaseCards[3]{industry, jobRole, useCase},
                realWorldStory{storyTitle, storyText, storyCompany},
                keyTakeaways[6]
```

Key names are kept exactly as in the sample, including the misspellings `expectebehavior`
and `dragandropp`, because the platform reads those names. IDs follow
`<course>-<level>-v1`, `…-mod-N`, `…-mod-N-lesson-M` and are set by code, not the LLM.

The sample is about 1.5 MB (64 lessons). One LLM call cannot produce that, so the
converter works in pieces like the old generator.

---

## 4. How the converter will work

```
 .txt / .docx / .pdf
        │
        ▼
 1. Extract text        txt: read (UTF-8, fallback encodings)
                        docx: python-docx paragraphs + headings + tables
                        pdf: pypdf page text (scanned PDFs rejected with a clear message)
        │
        ▼
 2. Clean and split     normalise whitespace, keep headings, split into sections
        │
        ▼
 3. Outline (1 call)    LLM reads the document and proposes course title, level,
                        modules and lesson titles, each tied to the source sections
        │
        ▼
 4. Course details      description, level, duration (1 call)
        │
        ▼
 5. Modules + lessons   1 call per module overview, 1 per lesson, sending only the
                        source sections for that lesson. Content checks + repair
                        calls from module_writer.py. Saved after each piece.
        │
        ▼
 6. Validate            full file against course_schema.json
        │
        ▼
 course JSON (download / output folder)
```

### Faithful to the source, filling gaps

The document is the source of truth. Explanations, concepts, examples and code should
come from it. Activities the document does not contain (quizzes, card matching, bug hunt,
etc.) are written by the LLM **based on that lesson's source text**. The prompt tells the
model not to add facts that are not in the source for content fields.

### Size options

The sample's 8 × 8 structure is the default, but a short document cannot fill 64 lessons.
The user can set modules and lessons per module (for example 2 × 3 for a demo).
In **auto** mode the outline step picks a size that fits the document's length.

### Switching LLM providers

One small interface, two implementations:

```python
class LLMProvider:
    def generate_json(self, prompt: str, schema: dict) -> dict: ...


GeminiProvider  # google-genai, response_json_schema   (default, free tier)
OpenAIProvider  # openai, response_format json_schema   (paid, optional)
```

Chosen in `.env`, no code change:

```env
LLM_PROVIDER=gemini            # or openai
GEMINI_API_KEY=...
GEMINI_MODEL=gemini-flash-latest
OPENAI_API_KEY=...             # only when LLM_PROVIDER=openai
OPENAI_MODEL=gpt-4o-mini
```

The web page and CLI can also override the provider per run. OpenAI's strict JSON-schema
mode has extra rules (every property required, `additionalProperties: false`), so the
OpenAI provider converts the schema before sending it.

### Free-tier limits

- Small requests (one lesson at a time) keep each response well under output limits.
- Wait and retry with growing delays when the API returns a rate-limit error (HTTP 429).
- Checkpoints mean a run that hits the daily limit can resume the next day.
- A full 8 × 8 conversion is about 75+ calls. Check current Gemini free-tier limits for the
  chosen model before the demo, and demo with a smaller size.

---

## 5. Project structure (target)

```
archintx-course-converter/
├── app/
│   ├── main.py              FastAPI app: upload page, /api/convert, /api/jobs/{id}, download, /healthz
│   ├── jobs.py              one-at-a-time background conversion jobs
│   └── static/              index.html, app.js, style.css
├── converter/
│   ├── cli.py               python -m converter.cli input.pdf -o out.json
│   ├── generate.py          original title-based generator (python -m converter.generate)
│   ├── extractors.py        txt / docx / pdf → blocks (headings + paragraphs), file limits
│   ├── chunking.py          blocks → sections
│   ├── pipeline.py          (from old pipeline.py)
│   ├── planner.py           (from old planner.py, document-based)
│   ├── module_writer.py     overview/lesson writing and repair calls
│   ├── lesson_checks.py     pure content checks split out of module_writer.py
│   ├── prompts.py           (from old, source-grounded prompts)
│   ├── providers/
│   │   ├── __init__.py      get_provider(settings) factory
│   │   ├── base.py          LLMProvider interface
│   │   ├── gemini.py        (from old gemini_service.py)
│   │   └── openai.py
│   ├── config.py            Settings object, load_settings(), limits
│   ├── schema_utils.py, validation.py, retry.py, checkpoint.py,
│   └── json_utils.py, user_input.py, exceptions.py
├── schema/course_schema.json
├── samples/
│   ├── javascript-beginner.json      reference output from the team
│   └── inputs/                       sample .txt, .docx, .pdf for tests and the demo
├── tools/generate_schema.py, tools/validate_json.py
├── tests/                   mirrors converter/ and app/ (test_<module>.py), conftest.py, fakes.py
├── docs/                    TECHNICAL.md, TEST_RESULTS.md, SPIKE_GEMINI.md, DEMO.md, examples/,
│                            LEGACY_GENERATOR.md
├── output/                  conversion results (git-ignored)
├── .github/workflows/ci.yml
├── pyproject.toml           ruff, pytest and coverage settings
├── .env.example, .gitignore, requirements.txt, requirements-dev.txt, render.yaml
├── README.md
└── PLAN.md
```

---

## 6. Build plan (step by step)

Each step is small enough for one focused session with an AI coding agent. A step is
finished only when its **Done when** check passes. Steps flagged
**[SECURITY]**, **[BUDGET]**, **[PERFORMANCE]** or **[DEADLINE]** touch a project constraint.

### 6.1 Assumptions and open questions

**Assumptions** (change them here if they are wrong):

1. Output keeps the sample's key names exactly, including `expectebehavior` and `dragandropp`.
2. Course size is configurable. Default is **auto** (fits the document); fixed sizes such as
   8 × 8 or 2 × 3 can be requested. Demos use 2 modules × 3 lessons to stay inside free-tier quota.
3. Input documents are mostly programming course material, like the sample. Code activities
   (syntax, bug hunt, code reordering) are always produced.
4. Team documents **may be confidential**. Gemini's free tier allows Google to use submitted
   content to improve its products (check the current terms), so the README and the upload page
   show a warning, and the paid OpenAI option is documented as the alternative.
5. The GitHub repository is **public** (needed for a shareable submission link). `.env` is never committed.
6. TODO notes use `TODO(team): <text> — see PLAN.md §<n>` until GitHub issues exist.
7. Python 3.14 from the existing `venv` is the runtime (the system also has 3.12; code stays 3.12-compatible).
8. Sample input documents in `samples/inputs/` are written by us (original text), so there are no copyright issues.
9. The live demo is protected by an access code so strangers cannot use up the Gemini quota.

**Open questions** (work can start without them, but they affect later steps):

1. **[DEADLINE]** What is the submission date? Steps 0–11 are the minimum for a working CLI with test results; 12–16 add the web demo and docs.
2. For non-programming documents, should code activities be dropped or filled with non-code content? (Assumption 3 until answered; affects Step 9.)
3. Does the team have an OpenAI key for one live test of Step 7? If not, OpenAI is tested with stubs only.

### 6.2 Conventions for every step

| Area | Rule |
|---|---|
| Style | PEP 8, enforced by `ruff check` and `ruff format`; settings in `pyproject.toml`; line length 100 |
| Naming | `snake_case` functions and modules, `PascalCase` classes, `UPPER_CASE` constants; domain words from the sample (course, module, lesson, section, outline) |
| Complexity | `ruff` rule C901, max complexity 10. Old functions above 10 are listed as per-file ignores with a TODO and removed in the step that touches them |
| Docstrings | Every public function, class and module, in the existing WHAT / WHY / RAISES style. Comments explain why, not what |
| Errors | Custom exceptions under `CourseGenerationError` (existing pattern). Only `GenerationError` and `ValidationFailedError` are retried. Unexpected exceptions keep their traceback |
| Logging | Python `logging`, one logger per module. **Never log** document text, prompts, model output, API keys or uploaded file contents. Log file name, size, page count, step, attempt number, timings |
| Settings | Read once at the entry point into a `Settings` object and passed in. No module reads environment variables at import time (from Step 6) |
| Tests | `pytest`; `tests/` mirrors `converter/` (`converter/extractors.py` → `tests/test_extractors.py`). Test files are built at runtime, not committed as binaries. No real network calls in the test suite |
| Coverage | ≥ 85% line coverage for new and refactored modules (`pytest-cov`) |
| Dependencies | Runtime packages in `requirements.txt`, dev tools in `requirements-dev.txt`, all pinned, checked with `pip-audit` |
| Scope | Out of scope for the whole project: OCR of scanned PDFs, `.doc`/`.rtf`/`.odt`, images in documents, keeping table layout (tables become text), user accounts |

### 6.3 Why this order

- **Step 0 first:** git, linting and pinned, audited dependencies are needed by every later step, and the retry bug wastes free-tier quota in any run.
- **Step 1 next because it is the biggest unknown:** whether the configured Gemini model accepts the lesson schema within free-tier limits. If it does not, the model choice or the design changes before anything is built on it. It needs no new code.
- **Steps 2–3 before new features:** the content checks are the most valuable old code. Tests lock their behaviour first, so the refactor (and every later change) cannot break them silently. They also show early whether the sample itself passes the checks.
- **Steps 4–5 (file reading) are independent and untrusted-input heavy**, so they come early and are tested on their own.
- **Step 6 (settings + provider interface) must come before any new LLM work**, because the planner, writer and pipeline must accept a fake provider to be testable at ₹0.
- **Steps 8–11 build the converter on top**, then prove it with real runs.
- **Web, CI, deployment and docs (12–16) come last** because they wrap a converter that already works.

### 6.4 Steps

#### Step 0 — Tooling baseline and quick fixes [SECURITY]
- **Goal:** Put the project under git with lint/format settings, install and pin dependencies, check them for known vulnerabilities, and fix the two issues found in review (unused imports, retry catching every exception).
- **Components/files:** `pyproject.toml` (new: ruff, pytest, coverage settings), `requirements.txt`, `requirements-dev.txt` (new: pytest, pytest-cov, ruff, pip-audit), `.gitignore`, `converter/retry.py`, `converter/user_input.py`, `tests/test_retry.py` (new). Create the GitHub repository and push.
- **Depends on:** nothing. (Folder reorganisation is already done.)
- **Done when:**
  - `git ls-files .env` prints nothing, and `git log -p | grep -cE "AIza[0-9A-Za-z_-]{35}"` prints `0` (the shape of a Gemini API key).
  - `ruff check .` and `ruff format --check .` pass.
  - `pip-audit -r requirements.txt -r requirements-dev.txt` reports no known vulnerabilities.
  - `pytest tests/test_retry.py` passes: a `KeyError` from the attempt is raised after **one** call; a `ValidationFailedError` is retried with its errors passed to the next attempt; the wait function is injected so the test does not sleep.

#### Step 1 — Gemini free-tier spike [BUDGET] [PERFORMANCE]
- **Goal:** Prove that the configured model returns a valid lesson for the lesson schema, and measure time, retries and quota use before building on it.
- **Components/files:** no new code. Run the existing generator (`python -m converter.generate --title "Spike" --difficulty beginner --duration 8`; 4 hours gives 1 module, below the minimum of 2) and stop it after 3 saved lessons or 15 minutes. Write `docs/SPIKE_GEMINI.md`. **Done 2026-11-20 — see that file.**
- **Depends on:** Step 0.
- **Done when:** `docs/SPIKE_GEMINI.md` records the model name, seconds per lesson, attempts per lesson, the model's current free-tier limits (requests per minute and per day, from AI Studio), the estimated number of calls for a 2 × 3 and an 8 × 8 course, and a decision: keep this model or switch. At least one lesson is saved under `output/spike/`.

#### Step 2 — Tests that lock the existing content checks
- **Goal:** Capture what the checks in `module_writer.py` accept and reject, using the 64 real lessons in the sample, before anything is refactored.
- **Components/files:** `tests/test_module_writer.py` (new), `tests/conftest.py` (new: loads the sample).
- **Depends on:** Step 0.
- **Done when:** `pytest tests/test_module_writer.py` passes. Every sample lesson passes every check (any lesson that does not is listed in the test file with the reason), and for each check at least one deliberately broken lesson fails with the expected message.
- **Done 2026-11-20.** The rules were first aligned to the sample (the team's ideal): objectives have 3 points, syntax examples 1–6 lines, diagrams may have several start nodes or loops, code snippets are allowed as card-matching terms, and the Mermaid parser now reads labelled, dotted, thick and chained arrows. 56 of 64 sample lessons pass; the 8 that do not are genuine slips (7 give the answer away, 1 diagram has unconnected boxes) and are listed in `KNOWN_EXCEPTIONS` in the test file. Baseline coverage of `module_writer.py`: 85% (untested lines are the LLM-calling functions, covered in Step 6b).

#### Step 3 — Split the content checks and cut complexity
- **Goal:** Move the pure checks into their own module and split every function over 10 branches, without changing behaviour.
- **Components/files:** `converter/lesson_checks.py` (new), `converter/module_writer.py` (keeps writing and repair only), `tests/test_module_writer.py` → `tests/test_lesson_checks.py`.
- **Depends on:** Step 2.
- **Done when:** the Step 2 tests pass with only their import lines changed; `ruff check --select C901 converter/lesson_checks.py converter/module_writer.py` passes with max complexity 10; coverage of `lesson_checks.py` is ≥ 85%.
- **Done 2026-11-20.** Repairs moved into `lesson_checks.py` with the checks (not left in `module_writer.py` as first planned), because the Step 2 tests call them and could otherwise not pass with only the import changed. `lesson_structure_errors` now only checks; the writer calls `repair_and_check`. Commit `f8733d5` is the pure move (test diff: one import line). Coverage of `lesson_checks.py`: 96%.

#### Step 4 — Read .txt, .docx and .pdf files [SECURITY]
- **Goal:** `extract_blocks(path)` returns the document as ordered blocks (heading with level, or paragraph), with untrusted-file limits enforced.
- **Components/files:** `converter/extractors.py` (new), `converter/exceptions.py` (add `ExtractionError`), `converter/config.py` (limits), `tests/test_extractors.py`, `tests/conftest.py` (builds `.docx` with python-docx and PDFs from raw bytes / pypdf at test time).
- **Rules:** type checked by extension **and** first bytes (`%PDF-`, or a zip containing `word/document.xml`); ≤ 10 MB file; ≤ 200 PDF pages; `.docx` total unzipped size ≤ 50 MB (zip-bomb check before parsing); ≤ 500,000 characters of text; `.txt` decoded as UTF-8 (BOM allowed), then cp1252; password-protected and text-less (scanned) PDFs rejected with a clear message; error messages never include full server paths.
- **Depends on:** Step 0.
- **Done when:** `pytest tests/test_extractors.py --cov=converter.extractors --cov-fail-under=85` passes, covering: happy path for each format (docx headings and a table, a 2-page PDF); BOM, cp1252 and no-newline text; and rejection of empty, whitespace-only, unsupported, wrong-extension, oversized, too-many-pages, password-protected, scanned and zip-bomb files.
- **Done 2026-11-20.** 38 tests, 99% coverage. Changes from the plan: limits live in an `ExtractionLimits` object passed to `extract_blocks()` (defaults as above) instead of more import-time constants in `config.py`, so tests use small limits and Step 6a can put it in `Settings`; UTF-16 text with a byte-order mark is also read; PDFs with only an owner password (they open without one) are read, and only PDFs that need a password to open are rejected; a one-line Markdown heading (`## Loops`) in a `.txt` becomes a heading block. python-docx parses XML with `resolve_entities=False`, so Word files cannot use XML entity attacks. Known risk: a crafted PDF can still make `pypdf` slow; Step 12 runs extraction with a time limit.

#### Step 5 — Split text into sections
- **Goal:** `split_sections(blocks, max_chars)` groups blocks into sections (id, heading path, text) at headings, and splits long or heading-less text by length.
- **Components/files:** `converter/chunking.py` (new), `tests/test_chunking.py`.
- **Depends on:** Step 4.
- **Done when:** `pytest tests/test_chunking.py --cov=converter.chunking --cov-fail-under=85` passes, including a check that the joined text of all sections equals the joined text of all blocks (no text lost), that no section exceeds `max_chars`, and that section ids are stable for the same input.
- **Done 2026-11-20.** 22 tests, 99% coverage. A section's text starts with its own heading lines, so "no text lost" compares all text with whitespace ignored (a split can move a line break). Headings in a row open one section. Default `max_chars` is 3,000 (about one printed page). Long paragraphs split at a line break, then a sentence end, then a space, then mid-word, and never strip the next line's indentation.

#### Step 6a — Settings object and provider interface [SECURITY]
- **Goal:** Replace import-time configuration with a `Settings` object loaded once, and put Gemini behind an `LLMProvider` interface chosen by a small factory.
- **Components/files:** `converter/config.py` (`Settings`, `load_settings()`), `converter/providers/base.py` (new: `LLMProvider.generate_json(prompt, schema)`), `converter/providers/gemini.py`, `converter/providers/__init__.py` (`get_provider(settings, api_key=None)`), `tests/fakes.py` (new: `FakeProvider`), `tests/test_providers.py`.
- **Depends on:** Step 3.
- **Done when:** `grep -rnE "os\.getenv|os\.environ|load_dotenv" converter` matches only `config.py` inside `load_settings`; `grep -rn "providers.gemini" converter` matches only `providers/__init__.py`; tests pass for: right provider chosen by `LLM_PROVIDER`; unknown provider → `ConfigurationError`; missing key → error naming the variable, and the message never contains a key value.

#### Step 6b — Inject provider and settings; logging and progress
- **Goal:** `planner.py`, `module_writer.py` and `pipeline.py` receive the provider and settings as parameters; `print` is replaced by logging plus a `progress(event)` callback that the CLI and web app can use.
- **Components/files:** `converter/planner.py`, `converter/module_writer.py`, `converter/pipeline.py`, `converter/prompts.py`, `converter/user_input.py`, `converter/generate.py`, `tests/test_pipeline.py`.
- **Depends on:** Step 6a.
- **Done when:** `pytest tests/test_pipeline.py` runs the old title-based generator end to end with `FakeProvider` (2 modules × 2 lessons): the result validates against the schema, a simulated crash after lesson 2 resumes at lesson 3 without repeating provider calls, and no network is used. `grep -rn "print(" converter` matches only `generate.py`. Old C901 ignores for the touched functions are removed.

#### Step 7 — OpenAI provider [BUDGET]
- **Goal:** `OpenAIProvider` using JSON-schema structured output, with conversion of our schema to OpenAI's strict rules.
- **Components/files:** `converter/providers/openai.py` (new), `converter/providers/__init__.py`, `tests/test_openai_provider.py`, `.env.example`.
- **Depends on:** Step 6a. (Can be done any time after it; no other step depends on it.)
- **Done when:** tests pass with a stubbed OpenAI client: every object in the converted lesson schema has `additionalProperties: false` and lists all its properties as required; the request uses `response_format` of type `json_schema`; a refusal or empty response raises `GenerationError`; `LLM_PROVIDER=openai` without `OPENAI_API_KEY` gives a clear error. A live call is optional (Open question 3).

#### Step 8 — Outline from the document [SECURITY] [BUDGET]
- **Goal:** The planner reads the document's sections and returns course title, level, modules and lessons, each lesson citing the section ids it draws from. Size is auto or fixed. The document is passed as data, inside clear delimiters, with an instruction to ignore any instructions it contains.
- **Components/files:** `converter/planner.py`, `converter/prompts.py`, `samples/inputs/` (new: one short original programming tutorial as `.txt`, `.docx` and `.pdf`), `tests/test_planner.py`.
- **Depends on:** Steps 5 and 6b.
- **Done when:** `FakeProvider` tests pass for: lessons citing unknown section ids are rejected and retried; auto size stays within the module/lesson limits for a short and a long document; the document text appears only between the delimiters in the prompt. One real Gemini run on `samples/inputs/` produces an outline where every lesson cites at least one real section (result noted in `docs/TEST_RESULTS.md`).

#### Step 9 — Lessons written from their source sections [BUDGET] [PERFORMANCE]
- **Goal:** Overview and lesson prompts receive only the sections their outline entry cites. Content fields must come from that text; activities (quiz, card matching, etc.) are written from it.
- **Components/files:** `converter/prompts.py`, `converter/module_writer.py`, `tests/test_module_writer.py`.
- **Depends on:** Step 8.
- **Done when:** `FakeProvider` tests show that a lesson prompt contains its cited sections and none of the others, and stays under a set size limit. One real lesson generated from `samples/inputs/` passes all content checks, and a manual review (noted in `docs/TEST_RESULTS.md`) confirms its concepts and examples come from the source.

#### Step 10 — Conversion pipeline, resume and CLI
- **Goal:** `convert(path, options, provider, settings, progress)` runs extract → sections → outline → details → modules → lessons → validate. The checkpoint is keyed by the file's SHA-256 hash, IDs are set by code, and `totalDuration` is the sum of module durations. CLI: `python -m converter.cli INPUT [--modules N --lessons M | --auto] [--provider gemini|openai] [-o OUT]`.
- **Components/files:** `converter/pipeline.py`, `converter/checkpoint.py`, `converter/cli.py` (new), `tests/test_convert.py`, `tests/test_cli.py`.
- **Depends on:** Step 9.
- **Done when:** `FakeProvider` tests pass for: a 2 × 3 conversion that validates against `schema/course_schema.json`; a crash after lesson 2 that resumes at lesson 3 with no repeated calls; a changed input file that starts a fresh run; `totalDuration` equal to the module sum; CLI exit codes 0 (success), 1 (expected error), 2 (bad arguments) and 130 (Ctrl+C).

#### Step 11 — Real end-to-end runs [BUDGET] [PERFORMANCE]
- **Goal:** Convert the three sample inputs with Gemini at 2 × 3 and record the results.
- **Components/files:** `docs/examples/` (output JSON), `docs/TEST_RESULTS.md`.
- **Depends on:** Steps 1 and 10.
- **Done when:** all three outputs pass `python tools/validate_json.py docs/examples/<file>.json schema/course_schema.json`, and `docs/TEST_RESULTS.md` lists, per file: API calls, retries, total time, and the full `pytest` summary with coverage.

#### Step 12 — Web API [SECURITY] [PERFORMANCE] [BUDGET]
- **Goal:** FastAPI endpoints: `POST /api/convert` (upload + options), `GET /api/jobs/{id}` (progress), `GET /api/jobs/{id}/download`, `GET /healthz`. One job at a time, protected by an access code, temporary files removed after each job.
- **Components/files:** `app/main.py`, `app/jobs.py` (new), `tests/test_api.py`.
- **Rules:** size limit enforced while the upload is read, before it is saved; a pasted API key is kept in memory for that job only and never logged or stored; error responses give a short message and the job id, never a path or traceback; random job ids (`uuid4`); document extraction runs with a time limit (for example 60 s, in a separate process) because a crafted PDF can make `pypdf` very slow.
- **Depends on:** Step 10.
- **Done when:** `pytest tests/test_api.py` passes with `FakeProvider` for: upload → progress → download, and the result validates; 11 MB upload → 413; unsupported type → 415; wrong or missing access code → 401; a second job while one is running → 429; error bodies contain no file path or traceback; the temp folder is empty after a job; captured logs do not contain the test API key.

#### Step 13 — Upload page [SECURITY]
- **Goal:** One page with file picker, provider and size options, optional API key and access code fields, progress bar, JSON preview and download button, plus the confidentiality warning.
- **Components/files:** `app/static/index.html`, `app/static/app.js`, `app/static/style.css`, `app/main.py` (security headers).
- **Depends on:** Step 12.
- **Done when:** with `uvicorn app.main:app` running, the sample `.txt` converts in the browser and the downloaded JSON validates. `grep -n innerHTML app/static/app.js` prints nothing (model output is shown with `textContent` only, because fields such as `hooklineimage.html` come from the LLM). Responses carry a `Content-Security-Policy: default-src 'self'` header. The page works at 375 px width.

#### Step 14 — Continuous integration
- **Goal:** GitHub Actions runs ruff, pytest with coverage and pip-audit on every push and pull request.
- **Components/files:** `.github/workflows/ci.yml` (new), `README.md` (badge).
- **Depends on:** Step 0 (can be added early); most useful after Step 12.
- **Done when:** a push to GitHub shows a green run; a test branch with one failing test shows a red run.

#### Step 15 — Deploy the live demo [SECURITY] [BUDGET] [DEADLINE]
- **Goal:** Deploy to Render's free tier, with `GEMINI_API_KEY` and `DEMO_ACCESS_CODE` set as Render environment variables.
- **Components/files:** `render.yaml` (new), `README.md` (demo link).
- **Depends on:** Steps 13 and 14.
- **Done when:** `curl https://<app>.onrender.com/healthz` returns 200; the public page converts the sample `.txt` at 2 × 3 and the downloaded file validates; without the access code the API returns 401.

#### Step 16 — Documentation and demo [DEADLINE]
- **Goal:** Final README, `docs/TECHNICAL.md` (architecture diagram, pipeline, schema rules, prompt design, limits, security), final `docs/TEST_RESULTS.md`, a demo script, and a recorded walkthrough as a backup.
- **Components/files:** `README.md`, `docs/TECHNICAL.md`, `docs/TEST_RESULTS.md`, `docs/DEMO.md`.
- **Depends on:** Step 15.
- **Done when:** someone who has not worked on the project follows the README on a clean machine and runs the CLI and the test suite in under 15 minutes, and every item in section 8 (Submission checklist) is ticked.

### 6.5 Summary

| Step | Name | Depends on | Flags |
|---|---|---|---|
| 0 | Tooling baseline and quick fixes | — | SECURITY |
| 1 | Gemini free-tier spike | 0 | BUDGET, PERFORMANCE |
| 2 | Lock existing content checks | 0 | |
| 3 | Split checks, cut complexity | 2 | |
| 4 | Read .txt / .docx / .pdf | 0 | SECURITY |
| 5 | Split into sections | 4 | |
| 6a | Settings + provider interface | 3 | SECURITY |
| 6b | Inject dependencies, logging, progress | 6a | |
| 7 | OpenAI provider | 6a | BUDGET |
| 8 | Outline from the document | 5, 6b | SECURITY, BUDGET |
| 9 | Lessons from source sections | 8 | BUDGET, PERFORMANCE |
| 10 | Conversion pipeline, resume, CLI | 9 | |
| 11 | Real end-to-end runs | 1, 10 | BUDGET, PERFORMANCE |
| 12 | Web API | 10 | SECURITY, PERFORMANCE, BUDGET |
| 13 | Upload page | 12 | SECURITY |
| 14 | Continuous integration | 0 | |
| 15 | Deploy live demo | 13, 14 | SECURITY, BUDGET, DEADLINE |
| 16 | Documentation and demo | 15 | DEADLINE |

Steps 1, 2 and 4 depend only on Step 0 and can run in any order. Step 7 and Step 14 can be done whenever convenient after their dependency.

---

## 7. Testing plan

| Area | Tests |
|---|---|
| Extraction | Each format returns text; headings kept for docx; empty/scanned/unsupported/oversized files rejected |
| Chunking | Splits by headings; long sections split by length; no text lost |
| Provider | Factory picks the right provider; missing key error; OpenAI schema conversion produces valid strict schema |
| Validation | `javascript-beginner.json` passes; broken copies fail with the right paths |
| Content checks | Reused checks from `module_writer.py` (quiz index, card pairs, code order, Mermaid) |
| Pipeline | Fake provider: correct IDs, counts, resume after a simulated crash |
| End to end | Real Gemini run on `.txt`, `.docx`, `.pdf` samples at 2 × 3 size; output validates |
| Web API | Upload → job → progress → download, using FastAPI's test client and a fake provider |

Coverage target: ≥ 85% for new and refactored modules. The exact cases for each step are in
its **Done when** in section 6.4.

---

## 8. Submission checklist

- [ ] Source code in GitHub (public or shared with the team)
- [ ] GitHub repository link
- [ ] `README.md` + `docs/TECHNICAL.md`
- [ ] `docs/TEST_RESULTS.md` + pytest report + CI badge
- [ ] Live demo URL (Render) + sample input files + recorded walkthrough as a backup in case the free host is asleep or the quota runs out

---

## 9. Risks and mitigations

| Risk | Mitigation |
|---|---|
| Free-tier rate limit or daily quota hit during demo | Demo at small size; checkpoints; pre-recorded backup video; optional user-supplied key |
| Scanned PDFs have no text | Detect and show a clear message (OCR is out of scope at ₹0 hosting) |
| LLM invents content not in the document | Source-grounded prompts; send only relevant sections; content fields reviewed in tests |
| Long documents exceed context | Chunking; each lesson gets only its sections |
| Render free tier sleeps / restarts (loses files) | Results returned to the browser for download; jobs are short at demo size |
| API key leak | `.env` git-ignored; keys only in host environment variables; pasted keys never logged |
| OpenAI strict schema rules differ from Gemini's | Schema converter + tests |

---

## 10. Open questions

See section 6.1.
