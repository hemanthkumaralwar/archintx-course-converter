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
