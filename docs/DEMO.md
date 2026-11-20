# Live demonstration script (local)

Everything runs on your own computer. The only thing that goes online is the call to the
Gemini API. Total time: about 15 minutes, including two conversions of roughly 2 minutes each.

## Before the demo (10 minutes, the day before)

1. Open a terminal in the project folder and activate the environment:
   ```bash
   venv\Scripts\activate
   ```
   On macOS or Linux, use `source venv/bin/activate` instead.
2. Check `.env` has your Gemini key and a demo access code (any text you choose):
   ```env
   GEMINI_API_KEY=...
   DEMO_ACCESS_CODE=pick-a-code
   ```
3. Run the tests once; they should all pass:
   ```bash
   pytest -q
   ```
4. Do one practice conversion. It confirms your key and quota work, and it gives you a fresh
   result to show if the network fails during the demo:
   ```bash
   python -m converter.cli samples/inputs/python-basics.txt --modules 2 --lessons 3 -o demo-backup.json
   ```
5. Keep these open in tabs: `samples/javascript-beginner.json` (the team's sample),
   `samples/inputs/python-basics.pdf` (the input), `docs/examples/python-basics-pdf.json`
   (a finished output) and `docs/TEST_RESULTS.md`.

## The demo

### 1. The problem and the input (1 minute)

- Show the team's sample, `samples/javascript-beginner.json`: modules, lessons, quizzes,
  exercises, Mermaid diagrams. "Writing this by hand takes days."
- Show the input, `samples/inputs/python-basics.pdf`: an ordinary 3-page tutorial.

### 2. Convert from the command line (3 minutes)

Delete the earlier work folder first (`output/`), so the run starts fresh, then convert:

```bash
python -m converter.cli samples/inputs/python-basics.pdf --modules 2 --lessons 3 -o course.json
```

Point out, while it runs:
- each line `[n/10] ... (saved)` is one piece, saved as soon as it passes the checks;
- the outline lists which part of the document each lesson is written from.

Then show the result is valid:
```bash
python tools/validate_json.py course.json schema/course_schema.json
```
Open `course.json` next to the team's sample: same structure, same kinds of activities.

### 3. Stop and resume (1 minute)

Run a conversion of the `.docx`, press **Ctrl+C** after two or three `(saved)` lines, then run the
same command again. The finished pieces show `(already saved)` and it continues from the next one.

```bash
python -m converter.cli samples/inputs/python-basics.docx --modules 2 --lessons 3
```

(If you do not want to wait for this one to finish, stop it again; it is only for the resume.)

### 4. The web page (4 minutes)

```bash
uvicorn app.main:create_app --factory
```

Open <http://localhost:8000>:
1. Point at the warning about confidential documents.
2. Press **Use the sample document**, choose **2** modules and **3** lessons.
3. Enter a **wrong** access code and press **Convert**: "The access code is missing or wrong."
4. Enter the right code and convert. Show the progress bar, then the preview and **Download JSON**.
5. Optional: narrow the window to phone width; the page still fits.

Stop the server with **Ctrl+C**.

### 5. Quality and tests (2 minutes)

- `docs/TEST_RESULTS.md`: real Gemini runs for all three file types, with calls, retries and times.
- Run the tests:
  ```bash
  pytest -q
  ```
  452 tests in about a minute, with no network access (the LLM is replaced by a fake).

### 6. Questions to expect

| Question | Answer |
|---|---|
| Does it work offline? | Everything runs locally; only the LLM API call goes online. |
| Can it use OpenAI? | Yes: set `LLM_PROVIDER=openai` and `OPENAI_API_KEY` in `.env`. |
| What if the AI service is busy? | It waits and retries (15 s, 30 s). If it still fails, run the same command again; finished parts are kept. |
| Is the content made up? | Each lesson is written from the document sections it cites; the outline records which. |
| What does it cost? | ₹0 on Gemini's free tier (about 10 calls for a 2 × 3 course). |

## If something goes wrong during the demo

| Problem | What to do |
|---|---|
| "503" or "quota" errors | Show `demo-backup.json` and `docs/examples/`; explain that re-running continues from the last saved piece. |
| No internet | Show the backup output and run `pytest -q`, which needs no network. |
| Web page says conversions are switched off | `DEMO_ACCESS_CODE` is missing from `.env`; add it and restart the server. |
| "already saved" when you wanted a fresh run | Delete the `output/` folder (or use another `--output-dir`). |

## Recording the backup walkthrough

Record sections 2 and 4 (about 6 minutes) in case the live demo cannot run. On Windows, press
**Win + G** (Xbox Game Bar) and use **Capture**; OBS Studio is a free alternative. Save the video
next to the project, but do not add it to git (it is large).
