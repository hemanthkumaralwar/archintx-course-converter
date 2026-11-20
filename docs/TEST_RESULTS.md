# Test results

## Summary

| What | Result |
|---|---|
| Offline test suite (`pytest`) | **452 passed**, 96 % line and branch coverage, no network used (after Step 13) |
| Lint and security | `ruff` clean; `pip-audit` no known vulnerabilities |
| Real conversions (Gemini, 2 × 3) | `.txt`, `.docx` and `.pdf` all **VALID** against `schema/course_schema.json` (Step 11) |
| Web page (Step 13) | Sample converted in the browser with Gemini; downloaded course **VALID**; no console errors; works at 375 px |
| Resume after a stop | Confirmed against the real API (Step 11, PDF run) |
| Gemini free-tier calls used in testing | about 75 (spike, outlines, lessons, full runs, web page) |
| Open | Output-quality step 15Q paused for a decision; follow-ups F1–F3 in PLAN.md §6.6 |

The sections below are the real runs against the LLM, step by step, in the order they were done.

## Step 8 — Course outline from a document (Gemini)

**Date:** 2026-11-20 · **Model:** `gemini-3.1-flash-lite` · **Size requested:** 2 modules × 3 lessons
**Input:** `samples/inputs/python-basics.txt` and `.pdf` (the same original ~5,300-character tutorial)

**Done-when check:** every lesson must cite at least one section that exists. **Passed in all three runs.**

| Run | Input | Sections | Attempts | Time | Every lesson cites a real section | Sections not cited |
|---|---|---|---|---|---|---|
| 1 | `.txt` (headings) | 7 | 1 | 3.1 s | yes | none |
| 2 | `.pdf` (no headings), excerpts only | 3 | 1 | 1.4 s | yes | none |
| 3 | `.pdf`, full text (after the fix below) | 3 | 1 | 2.8 s | yes | none |

### Run 1 — `.txt`

Course title: *Python Basics for Complete Beginners* · level: beginner

| Module | Lesson | Sections |
|---|---|---|
| Core Data and Variables | Introduction to Python Variables | s1, s2 |
| | Numbers and Arithmetic Operations | s3 |
| | Working with Text and Strings | s4 |
| Control Flow and Program Structure | Making Decisions with If Statements | s5 |
| | Repeating Work with Loops | s6 |
| | Putting It All Together | s7 |

Each lesson matches one chapter of the document (s1 is the introduction, s2–s7 the six chapters).

### Run 2 — `.pdf`, outline shown only the first 600 characters of each section

PDF text has no heading styles, so the document became 3 sections of about 2,000
characters each. With excerpts only, the model could not see most of each section:

| Module | Lesson | Sections |
|---|---|---|
| Foundations of Python Programming | Introduction to Variables | s1 |
| | Working with Numbers and Types | s1 |
| | String Manipulation and Formatting | s2 |
| Control Flow and Iteration | **Advanced String Methods** | s2 |
| | For Loops and Ranges | s3 |
| | **While Loops and Conditional Logic** | s3 |

Problems: an invented "Advanced String Methods" lesson in the control-flow module,
and no lesson for the document's chapter on `if` statements.

**Fix:** documents up to 60,000 characters (`OUTLINE_FULL_TEXT_CHARS`, about 15,000
tokens) are now shown to the outline step in full; only larger documents use
600-character excerpts.

### Run 3 — `.pdf`, full text

| Module | Lesson | Sections |
|---|---|---|
| Data and Variables | Introduction to Variables | s1 |
| | Numbers and Arithmetic Operations | s1 |
| | Working with Text and Strings | s2 |
| Control Flow and Loops | Making Decisions with if Statements | s2 |
| | Repeating Work with for Loops | s3 |
| | While Loops and Putting It Together | s3 |

The outline now follows the document's own chapters, like the `.txt` run.

### Not yet verified

- Documents larger than 60,000 characters (the excerpt path) have not been run
  against the real model; that path is covered by offline tests only.
- The `.docx` sample was not sent to the model. Its extracted sections are the
  same 7 as the `.txt` (checked offline).

## Step 9 — One lesson written from its cited section (Gemini)

**Date:** 2026-11-20 · **Model:** `gemini-3.1-flash-lite`
**Lesson:** module 2, lesson 1, "Making Decisions with If Statements", from the Step 8
`.txt` outline. It cites one section, **s5** ("Making Decisions with if", 971 characters).
The module overview was given the module's sections s5–s7.
**Saved lesson:** [`docs/examples/step9-lesson-if-statements.json`](examples/step9-lesson-if-statements.json)

| Call | Time | Prompt size | Attempts |
|---|---|---|---|
| Course details | 2.9 s | 680 chars | 1 |
| Module 2 overview (sections s5–s7) | 4.2 s | 7,821 chars | 1 |
| Lesson 2.1 (section s5) | 14.6 s | 14,617 chars | 1 |

**Done-when check:** the lesson passes every content check (0 problems) and the lesson
schema (0 problems), with no rejected attempts and no repair calls. **Passed.**

### Manual review against the source (section s5)

| Lesson part | Taken from the source? |
|---|---|
| Explanation (6 points) | Yes: if runs a block when true, colon and four-space indentation, `elif` checked in order, `else` as the catch-all, the six comparison operators, `and` / `or` / `not`. All six points restate the section. |
| Concepts (8) | Yes: all eight are terms the section uses (indentation, comparison operators, elif, else, logical operators...). |
| Syntax and parts | Yes: the `if` / `elif` / `else` shape the section shows. |
| Example 3 | Yes: the section's own temperature example (hot over 30, warm over 20, else something else), slightly shortened. |
| Examples 1, 2, 4, 5 | Added, consistent with the source: pass mark, adult or minor, office hours with `and`, `!=` status check. |
| Bug hunt | Yes: the section's "common beginner mistake", `=` instead of `==`. |
| Quiz | Facts all match the source ("as many `elif` as you need", "only the first true block runs", `=` vs `==`). |
| Analogy, story, use cases | Added (traffic light controller, etc.), as the grounding rule allows. |

Nothing in the lesson contradicts the source, and nothing comes from another lesson's topic.

### Quality issues found (not caught by automatic checks)

1. **Quiz questions are mostly recall**, such as "Which operator checks if two values
   are NOT equal?". The prompt's quality rules ask for scenario-based questions that
   test application. To look at in Step 11 (prompt wording, or a check).
2. **One ambiguous quiz answer:** "check if x is between 10 and 20" gives
   `x > 10 and x < 20`, which excludes 10 and 20 without saying so.

## Step 11 — End-to-end conversions of the three sample files (Gemini)

**Date:** 2026-11-20 · **Model:** `gemini-3.1-flash-lite` · **Size:** 2 modules × 3 lessons
**How:** the real command line (`converter.cli.main`) for each file, with a counting
wrapper around the Gemini provider (outside the repository) to record every call:

```bash
python -m converter.cli samples/inputs/python-basics.<ext> --modules 2 --lessons 3 -o docs/examples/python-basics-<ext>.json
```

**Done-when check:** all three outputs pass
`python tools/validate_json.py docs/examples/<file>.json schema/course_schema.json`. **Passed.**

| File | Output | API calls | Failed calls (503) | Retries | Repair calls | Total time | Result |
|---|---|---|---|---|---|---|---|
| `python-basics.txt` | [`python-basics-txt.json`](examples/python-basics-txt.json) | 10 | 0 | 0 | 0 | 98 s | VALID |
| `python-basics.docx` | [`python-basics-docx.json`](examples/python-basics-docx.json) | 12 | 2 | 2 | 0 | 185 s | VALID |
| `python-basics.pdf`, run 1 | — | 7 | 3 | 2 | 0 | 73 s | stopped (exit 1) |
| `python-basics.pdf`, run 2 (resumed) | [`python-basics-pdf.json`](examples/python-basics-pdf.json) | 6 | 0 | 0 | 0 | 86 s | VALID |
| **Total** | | **35** | **5** | **4** | **0** | **7 min 22 s** | |

Every lesson in all three courses passes every content check (0 problems), and each
course's `totalDuration` (3 hours) equals the sum of its modules (1 hour 30 minutes each).

### What happened with the PDF

During the run Gemini answered several calls with `503 UNAVAILABLE`, "This model is
currently experiencing high demand". The retry logic then waited only 2 s and 4 s,
so lesson 1.2 of the PDF failed three times in a row and the run stopped with a
one-line error (exit code 1). The finished pieces were kept.

- **Fix:** after an API failure the converter now waits 15 s, then 30 s (doubling),
  and a validation failure is retried at once, since waiting cannot fix it
  (`converter/retry.py`, `RETRY_DELAY_SECONDS` in `converter/config.py`, tests in
  `tests/test_retry.py`).
- **Resume, tested for real:** running the same command again reused the outline,
  course details, module 1 overview and lesson 1.1 (`already saved`) and wrote only
  the 6 remaining pieces, with no repeated calls.

### Outlines produced

| File | Module 1 | Module 2 |
|---|---|---|
| `.txt` | Variables and Assignment · Numbers and Arithmetic · Working with Text | Making Decisions with if · Repeating Work with Loops · Putting It Together |
| `.docx` | Introduction to Variables and Assignment · Performing Calculations with Numbers · Manipulating Text and Strings | Making Decisions with If Statements · Repeating Tasks with Loops · Building a Complete Python Program |
| `.pdf` | Introduction to Variables and Assignment · Working with Numbers and Arithmetic · String Manipulation and Formatting | Making Decisions with If Statements · Repeating Work with For Loops · While Loops and Putting It Together |

All three follow the document's own chapters.

### Quality issues found (not caught by automatic checks)

1. **Lesson durations are written as a range**, "25-30 minutes", in all 18 lessons,
   because the prompt gives the target as a range. The sample uses one value
   ("25 minutes"). The duration code reads such a range as 30 minutes, so totals stay
   consistent. Fix: ask for a single value in the prompt.
2. **Quiz questions are mostly recall**, as in Step 9: a rough check (long or
   situation-based wording) finds 1 to 6 scenario-style questions out of 10 per lesson.
   Fix: stronger quiz wording in the prompt, possibly with an example question.

Both are prompt changes that need new Gemini runs to confirm; they are not part of this step.

### Offline test suite

Run after the retry fix: `pytest --cov=converter` → **396 passed**, **96% coverage**
(lines and branches). Lint (`ruff check`, `ruff format --check`) clean;
`pip-audit` finds no known vulnerabilities.

| Module | Coverage | Module | Coverage |
|---|---|---|---|
| `checkpoint.py` | 100% | `planner.py` | 100% |
| `chunking.py` | 99% | `prompts.py` | 100% |
| `cli.py` | 97% | `providers/__init__.py` | 100% |
| `config.py` | 100% | `providers/base.py` | 100% |
| `convert.py` | 100% | `providers/gemini.py` | 100% |
| `exceptions.py` | 100% | `providers/openai.py` | 100% |
| `extractors.py` | 99% | `retry.py` | 100% |
| `generate.py` | 92% | `schema_utils.py` | 80% |
| `json_utils.py` | 65% | `user_input.py` | 100% |
| `lesson_checks.py` | 97% | `validation.py` | 90% |
| `module_writer.py` | 98% | **Total** | **96%** |
| `pipeline.py` | 92% | | |

`json_utils.py` and `schema_utils.py` are older modules from the title-based generator;
their uncovered lines are error branches (unreadable files, malformed schemas).
