# Test results

Results of real runs against the LLM, step by step. Offline test-suite results
(pytest, coverage) are added in Step 11.

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
