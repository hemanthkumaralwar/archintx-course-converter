# Gemini free-tier spike (PLAN.md Step 1)

**Date:** 2026-11-20 · **Question:** can the configured Gemini model produce lessons that match
the lesson schema and content checks, within free-tier limits, before we build on it?

**Answer: yes.** Every call succeeded on the first attempt, and every saved lesson passed both the
schema and the content checks.

## How it was run

No new code. The original generator was run with each output line timestamped, and stopped
automatically after 3 saved lessons (limit: 3 lessons or 15 minutes):

```bash
python -u -m converter.generate --title "Spike" --difficulty beginner --duration 8
```

`--duration 8` was used because 4 hours gives 1 module, below the generator's minimum of 2.
The plan's original `--duration 4` command was corrected here.

- **Model:** `gemini-3.1-flash-lite` (from `.env`, `GEMINI_MODEL`)
- **Temperature:** 0.3 · **Retries:** up to 3 attempts per step, up to 2 repair calls per lesson
- **Output:** `output/spike/` (git-ignored)

## Results

| Step | Calls | Attempts | Time |
|---|---|---|---|
| Course plan (2 modules × 8 lesson titles) + course details | 2 | 1 each | 10 s for both |
| Module 1 overview + lesson 1.1 | 2 | 1 each | 53 s for both |
| Lesson 1.2 | 1 | 1 | 13 s |
| Lesson 1.3 | 1 | 1 | 16 s |
| **Total** | **6** | **no retries, no repairs** | **100 s** |

Timestamped log:

```
11:10:34 Modules planned: 2 for 8 hours
11:10:44 Module 1/2: Foundations of Spike Architecture
11:11:37   Lesson 1.1: What is a Spike: Defining the Core Concept (saved)
11:11:50   Lesson 1.2: The Anatomy of a Spike Signal (saved)
11:12:06   Lesson 1.3: Hardware Requirements for Spike Detection (saved)
11:12:08 STOP saved_lessons=3 elapsed=100s
```

Quality checks on the saved lessons:

| Lesson | Content-check errors | Schema errors | Size | Approx. output tokens (chars ÷ 4) |
|---|---|---|---|---|
| 1.1 | 0 | 0 | 17,017 chars | ~4,250 |
| 1.2 | 0 | 0 | 16,452 chars | ~4,100 |
| 1.3 | 0 | 0 | 16,939 chars | ~4,230 |

For comparison, the team's sample lessons average 15,493 characters. `output/spike/errors/` is empty.

## Limits not measured here

- **Input tokens per call:** the old code does not log the API's usage figures. Step 6b's logging
  should record `usage_metadata` (token counts only, never prompt text).
- **Lesson time on its own vs with the module overview:** lesson 1.1 includes the overview call,
  so steady-state lesson time is taken from lessons 1.2–1.3 (13–16 s).
- **Free-tier rate limits for this model:** Google's public rate-limits page
  (aistudio.google.com/docs/rate-limits) does **not** list free-tier numbers for Flash-Lite models.
  It says limits are applied **per project**, vary by model and usage tier, are shown in
  **Google AI Studio**, and daily quotas reset at midnight Pacific time.
  **Action for the project owner:** open AI Studio → rate limits, and write the RPM and RPD for
  `gemini-3.1-flash-lite` here.

| Limit | Value for this project |
|---|---|
| Requests per minute (RPM) | _fill in from AI Studio_ |
| Requests per day (RPD) | _fill in from AI Studio_ |

## Estimated calls per conversion

Formula: 1 outline + 1 course details + 1 overview per module + 1 per lesson, multiplied by
retries when output is rejected (worst case per lesson: 3 attempts × (1 + 2 repairs) = 9 calls).

| Course size | Calls (no retries, as in this spike) | Worst case | Time (at ~15 s per call) |
|---|---|---|---|
| 2 modules × 3 lessons | 2 + 2 + 6 = **10** | ~58 | ~2.5 min |
| 8 modules × 8 lessons | 2 + 8 + 64 = **74** | ~600 | ~19 min |

A full 8 × 8 course fits in one day only if the project's RPD is comfortably above 74. Demos
should use 2 × 3, as planned.

## Findings that affect later steps

1. **The old content rules match Gemini's output, not the team's sample.** All 3 generated lessons
   pass the checks (4-point objectives, single-root diagrams, 2–6 line syntax), but all 64 sample
   lessons fail them (the sample uses 3-point objectives, multi-root diagrams, longer syntax). The
   prompts tell the model these rules, so it follows them. **Step 2 must decide which rules are
   right**: the sample's (the team's "ideal") or the old code's.
2. **Privacy:** Google's pricing page says free-tier content is used to improve Google's products
   (confirmed on the page for Gemini 3.5 Flash-Lite; the 3.1 Flash-Lite entry was not visible).
   This supports PLAN.md assumption 4: warn users not to upload confidential documents on the free tier.
3. **Model name mismatch:** `.env` uses `gemini-3.1-flash-lite`, but `.env.example` said
   `gemini-3.5-flash-lite`. `.env.example` is now set to the tested model.
4. **The plan title is taken literally:** "Spike" was planned as a course about signal spikes. The
   converter avoids this by planning from the document's content instead of a title.

## Decision

**Keep `gemini-3.1-flash-lite`.** It produced valid, sample-sized lessons on the first attempt at
about 15 seconds per lesson. Revisit only if AI Studio shows an RPD too low for the planned demo
sizes (under ~100), or if Step 11's real conversions show more retries than this spike.
