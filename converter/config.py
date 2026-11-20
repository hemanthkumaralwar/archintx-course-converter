"""
config.py

WHAT: Project-wide settings:
      - constants that stay the same from one course to the next (schema
        file, output folder, course structure, retry limits),
      - Settings: values that come from the environment or .env (LLM
        provider, API key, model), read once by load_settings().

WHY:  Course title, difficulty, and duration are NOT stored here. The user
      supplies them on each run (see user_input.py). Environment values are
      read only when load_settings() is called, never at import, so nothing
      else in the code depends on the environment.
"""

import os
from dataclasses import dataclass, field
from pathlib import Path

from dotenv import dotenv_values

from .exceptions import ConfigurationError

# ------------------------------------------------------------
# Files and folders
# ------------------------------------------------------------

# Project root (the folder that holds converter/, schema/, output/).
# WHY: paths work no matter which folder the program is started from.
PROJECT_ROOT = Path(__file__).resolve().parent.parent

# Holds the API key. Git ignores it (see .gitignore).
DEFAULT_ENV_FILE = PROJECT_ROOT / ".env"

# Every output must follow this schema.
SCHEMA_FILE = PROJECT_ROOT / "schema" / "course_schema.json"

# Each course gets its own subfolder inside this one.
OUTPUT_ROOT = PROJECT_ROOT / "output"

# Optional overrides for the array locations. Leave as None to detect them
# automatically from the schema.
#   ARRAY_PATH:        path to the module list, such as "course.modules"
#   LESSON_ARRAY_PATH: path to the lesson list inside one module, such as "lessons"
ARRAY_PATH = None

# Set explicitly: automatic search would pick "moduleExplanation" first.
LESSON_ARRAY_PATH = "lessons"


# ------------------------------------------------------------
# Course structure
# ------------------------------------------------------------

# Accepted difficulty values. Anything else is rejected at input time.
DIFFICULTY_LEVELS = ("beginner", "intermediate", "advanced")

# Every module contains exactly this many lessons.
LESSONS_PER_MODULE = 8

# Numbered points inside each lesson's "objective" text, written as (1), (2), ...
# 3 because every lesson in samples/javascript-beginner.json (the team's ideal) has 3.
OBJECTIVE_POINTS = 3

# Lines of code allowed in the syntax example. The sample uses 1 to 5 lines.
SYNTAX_LINES_MIN = 1
SYNTAX_LINES_MAX = 6

# Exact item counts inside EACH lesson. Keys are paths inside a lesson.
# Card matching uses 12 cards that form 6 pairs (term and its description).
LESSON_ITEM_COUNTS = {
    "concepts": 8,  # Core Concepts
    "quiz": 10,  # Quiz questions
    "codereordering.codelines": 6,
    "codereordering.correctOrder": 6,
    "cardmatching.cards": 12,
    "cardmatching.matches": 6,
    "dragandropp.items": 6,
    "parts": 8,  # Step 1 to Step 8
    "example": 5,  # Example 1 to Example 5
    "hooklines": 2,
    "keyTakeaways": 6,
    "useCaseCards": 3,
    "lessonExplanation": 1,  # Exactly one topic block
}

# Target length of one lesson, in minutes. The prompt asks for this range.
LESSON_MINUTES_MIN = 25
LESSON_MINUTES_MAX = 30

# Minutes used to convert the requested hours into a module count.
# Using the top of the range means the course is never shorter than the
# requested hours. Shorter lessons would make the course a little shorter.
PLANNING_LESSON_MINUTES = LESSON_MINUTES_MAX

# Safety limits on the number of modules, so an accidental very large
# duration does not start hundreds of API calls.
MIN_MODULES = 2
MAX_MODULES = 30


# ------------------------------------------------------------
# Generation settings
# ------------------------------------------------------------

# Attempts per request before the run stops.
MAX_RETRIES = 3

# Base wait between attempts. It grows with each attempt.
RETRY_DELAY_SECONDS = 2

# Lower values give more predictable output. Gemini accepts 0 to 2.
TEMPERATURE = 0.3


# ------------------------------------------------------------
# Settings from the environment (LLM provider, API key, model)
# ------------------------------------------------------------

DEFAULT_PROVIDER = "gemini"

# The model tested in docs/SPIKE_GEMINI.md.
DEFAULT_GEMINI_MODEL = "gemini-3.1-flash-lite"

# Matches .env.example. Not tested live (no OpenAI key at ₹0 budget); set
# OPENAI_MODEL to any current model that supports JSON-schema output.
DEFAULT_OPENAI_MODEL = "gpt-4o-mini"


@dataclass(frozen=True)
class Settings:
    """
    WHAT: Values read from the environment and .env for one run.

    WHY:  API keys are excluded from repr, so printing or logging a Settings
          object (or a traceback that shows it) never reveals a key.
    """

    llm_provider: str = DEFAULT_PROVIDER
    gemini_api_key: str = field(default="", repr=False)
    gemini_model: str = DEFAULT_GEMINI_MODEL
    openai_api_key: str = field(default="", repr=False)
    openai_model: str = DEFAULT_OPENAI_MODEL
    temperature: float = TEMPERATURE


def load_settings(environ=None, env_file=DEFAULT_ENV_FILE):
    """
    WHAT: Read Settings from the environment and the .env file.

    HOW:  Variables already set in the environment win over the .env file
          (the usual rule for .env files). Blank values count as missing.

    WHY:  The .env file is read with dotenv_values, which does not change
          os.environ, so loading settings has no side effects. Tests pass
          their own `environ` and `env_file`.

    RETURNS:
        A Settings object. It is not checked for a usable API key here;
        providers.get_provider does that, because it knows which key it needs.
    """
    file_values = dotenv_values(env_file) if env_file and Path(env_file).is_file() else {}
    values = {**file_values, **(os.environ if environ is None else environ)}

    def read(name):
        return (values.get(name) or "").strip()

    return Settings(
        llm_provider=read("LLM_PROVIDER").lower() or DEFAULT_PROVIDER,
        gemini_api_key=read("GEMINI_API_KEY"),
        gemini_model=read("GEMINI_MODEL") or DEFAULT_GEMINI_MODEL,
        openai_api_key=read("OPENAI_API_KEY"),
        openai_model=read("OPENAI_MODEL") or DEFAULT_OPENAI_MODEL,
    )


def validate_config():
    """
    WHAT: Checks that the constants above are usable before any API call is made.

    WHY:  A broken setting or missing schema should stop the run in seconds,
          not after several requests.

    RAISES:
        ConfigurationError: for the first setting that is invalid.
    """
    if not SCHEMA_FILE.is_file():
        raise ConfigurationError(f"Schema file not found: {SCHEMA_FILE}")

    for is_valid, message in _constant_rules():
        if not is_valid:
            raise ConfigurationError(message)


def _constant_rules():
    """Return (is_valid, message) for every rule the constants above must follow."""
    paths = (("ARRAY_PATH", ARRAY_PATH), ("LESSON_ARRAY_PATH", LESSON_ARRAY_PATH))
    rules = [
        (value is None or bool(str(value).strip()), f"{name} is set but empty. Use None or a path.")
        for name, value in paths
    ]
    rules += [
        (
            isinstance(count, int) and count >= 1,
            f"LESSON_ITEM_COUNTS['{item_path}'] must be a whole number of at least 1.",
        )
        for item_path, count in LESSON_ITEM_COUNTS.items()
    ]
    rules += [
        (
            1 <= SYNTAX_LINES_MIN <= SYNTAX_LINES_MAX,
            f"SYNTAX_LINES_MIN/MAX are invalid: {SYNTAX_LINES_MIN}-{SYNTAX_LINES_MAX}.",
        ),
        (
            LESSONS_PER_MODULE >= 1,
            f"LESSONS_PER_MODULE must be at least 1 (got {LESSONS_PER_MODULE}).",
        ),
        (
            1 <= LESSON_MINUTES_MIN <= LESSON_MINUTES_MAX,
            f"Lesson length range is invalid: {LESSON_MINUTES_MIN}-{LESSON_MINUTES_MAX} minutes.",
        ),
        (
            LESSON_MINUTES_MIN <= PLANNING_LESSON_MINUTES <= LESSON_MINUTES_MAX,
            "PLANNING_LESSON_MINUTES must be within the lesson length range.",
        ),
        (
            1 <= MIN_MODULES <= MAX_MODULES,
            f"Module limits are invalid: MIN_MODULES={MIN_MODULES}, MAX_MODULES={MAX_MODULES}.",
        ),
        (MAX_RETRIES >= 1, f"MAX_RETRIES must be at least 1 (got {MAX_RETRIES})."),
        (
            RETRY_DELAY_SECONDS >= 0,
            f"RETRY_DELAY_SECONDS cannot be negative (got {RETRY_DELAY_SECONDS}).",
        ),
        (0 <= TEMPERATURE <= 2, f"TEMPERATURE must be between 0 and 2 (got {TEMPERATURE})."),
    ]
    return rules
