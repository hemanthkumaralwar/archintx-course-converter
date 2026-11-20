"""
Tests that lock the lesson content checks in converter/module_writer.py.

The rules follow samples/javascript-beginner.json, the team's ideal output:
every sample lesson must pass, except the known slips listed below.
"""

import copy

import pytest

from converter import module_writer as mw
from tests.sample_course import SAMPLE_LESSONS

# Sample lessons that break a rule the team's format still needs. Each one is a
# slip in the sample, not a reason to drop the rule.
KNOWN_EXCEPTIONS = {
    # Drag-and-drop item text names its own bucket, which gives the answer away.
    "javascript-beginner-mod-2-lesson-8": [
        "dragandropp.items[1] content names its bucket 'Block'",
    ],
    "javascript-beginner-mod-4-lesson-7": [
        "dragandropp.items[1] content names its bucket 'find'",
    ],
    "javascript-beginner-mod-7-lesson-1": [
        "dragandropp.items[0] content names its bucket 'once'",
    ],
    "javascript-beginner-mod-7-lesson-3": [
        "dragandropp.items[0] content names its bucket 'click'",
        "dragandropp.items[4] content names its bucket 'click'",
    ],
    # Card-matching description repeats its own term, which gives the answer away.
    "javascript-beginner-mod-4-lesson-5": [
        "cardmatching.matches[5] description names its own term 'every'",
    ],
    "javascript-beginner-mod-6-lesson-7": [
        "cardmatching.matches[1] description names its own term 'children'",
    ],
    "javascript-beginner-mod-7-lesson-5": [
        "cardmatching.matches[3] description names its own term 'focus'",
    ],
    # Two boxes with no arrow between them: the diagram shows no relationship.
    "javascript-beginner-mod-7-lesson-6": [
        "hooklines[0] hooklineimage diagram has disconnected nodes: A, B",
    ],
}


def mermaid_block(*lines):
    return "```mermaid\n" + "\n".join(lines) + "\n```"


# ---------------------------------------------------------------------------
# The team's sample
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("sample_lesson", SAMPLE_LESSONS, ids=lambda item: item["lessonId"][20:])
def test_sample_lesson_passes_every_check(sample_lesson):
    lesson = copy.deepcopy(sample_lesson)

    errors = mw.lesson_structure_errors(lesson)

    assert errors == KNOWN_EXCEPTIONS.get(sample_lesson["lessonId"], [])
    assert lesson == sample_lesson, "repairs must not change a valid lesson"


def test_known_exceptions_all_exist():
    ids = {item["lessonId"] for item in SAMPLE_LESSONS}

    assert set(KNOWN_EXCEPTIONS) <= ids


# ---------------------------------------------------------------------------
# Objective
# ---------------------------------------------------------------------------

OBJECTIVE = "By the end of this lesson, you will be able to: (1) a, (2) b, (3) c."


def test_objective_with_three_points_passes():
    assert mw.check_objective(OBJECTIVE, 3) == []


def test_objective_missing_point():
    assert mw.check_objective("You will: (1) a, (2) b.", 3) == [
        "objective is missing numbered point (3)"
    ]


def test_objective_extra_point():
    assert mw.check_objective(OBJECTIVE + " (4) d.", 3) == [
        "objective has more than 3 numbered points"
    ]


def test_objective_not_text():
    assert mw.check_objective(None, 3) == ["objective must be text"]


def test_lesson_uses_configured_three_points(lesson):
    lesson["objective"] = OBJECTIVE + " (4) d."

    assert "objective has more than 3 numbered points" in mw.lesson_structure_errors(lesson)


# ---------------------------------------------------------------------------
# Code reordering
# ---------------------------------------------------------------------------


def reorder_section(lines, order):
    return {"codelines": lines, "correctOrder": order}


SHUFFLED = ["// 2. b", "// 1. a", "// 3. c"]


def test_code_reorder_valid():
    assert mw.check_code_reorder(reorder_section(SHUFFLED, ["1", "0", "2"])) == []


@pytest.mark.parametrize("section", [None, {}, {"codelines": "x", "correctOrder": []}])
def test_code_reorder_missing_section_is_left_to_schema(section):
    assert mw.check_code_reorder(section) == []


def test_code_reorder_line_without_step_number():
    errors = mw.check_code_reorder(reorder_section(["// 2. b", "a", "// 3. c"], ["1", "0", "2"]))

    assert errors == [
        'codereordering.codelines must start with a step number such as "// 1." '
        "(missing on line index 1)"
    ]


def test_code_reorder_repeated_step_number():
    errors = mw.check_code_reorder(reorder_section(["// 2. b", "// 2. a", "// 3. c"], []))

    assert errors == ["codereordering step numbers must be 1 to 3, each used once"]


def test_code_reorder_already_in_order_and_wrong_order_list():
    errors = mw.check_code_reorder(reorder_section(["// 1. a", "// 2. b", "// 3. c"], ["2"]))

    assert errors == [
        "codereordering.codelines are already in step order; shuffle them",
        "codereordering.correctOrder must be ['0', '1', '2']: the index of each "
        "line, in step-number order",
    ]


def test_repair_code_reorder_shuffles_sorted_lines_and_rebuilds_order():
    section = reorder_section(["// 1. a", "// 2. b", "// 3. c"], ["9"])

    mw.repair_code_reorder(section)

    assert section == {
        "codelines": ["// 3. c", "// 2. b", "// 1. a"],
        "correctOrder": ["2", "1", "0"],
    }
    assert mw.check_code_reorder(section) == []


def test_repair_code_reorder_fixes_wrong_order_only():
    section = reorder_section(list(SHUFFLED), ["0", "1", "2"])

    mw.repair_code_reorder(section)

    assert section == reorder_section(SHUFFLED, ["1", "0", "2"])


@pytest.mark.parametrize(
    "lines",
    [[], ["// 1. a", "no number"], ["// 1. a", "// 1. b"]],
    ids=["empty", "unnumbered", "repeat"],
)
def test_repair_code_reorder_leaves_unfixable_sections(lines):
    section = reorder_section(list(lines), ["x"])

    mw.repair_code_reorder(section)

    assert section == reorder_section(lines, ["x"])


# ---------------------------------------------------------------------------
# Drag and drop
# ---------------------------------------------------------------------------


def drag_section(items, buckets=("const", "let")):
    return {
        "items": [
            {"id": str(number), "content": content, "correctCategory": bucket}
            for number, (content, bucket) in enumerate(items, start=1)
        ],
        "correctpairs": list(buckets),
    }


GOOD_ITEMS = [("A value read once at startup", "const"), ("A loop counter", "let")]


def test_drag_drop_valid():
    assert mw.check_drag_drop(drag_section(GOOD_ITEMS)) == []


def test_drag_drop_unknown_bucket():
    errors = mw.check_drag_drop(drag_section([*GOOD_ITEMS, ("A setting", "var")]))

    assert errors == [
        "dragandropp.items[2] correctCategory 'var' is not one of the buckets in correctpairs"
    ]


def test_drag_drop_bucket_rules():
    errors = mw.check_drag_drop(drag_section([("A value", "const")], buckets=("const", "const")))

    assert errors == [
        "dragandropp.correctpairs repeats a bucket name",
        "dragandropp.correctpairs must name at least 2 buckets",
        "dragandropp items must use at least 2 different buckets",
    ]


def test_drag_drop_bucket_names_must_be_text():
    assert mw.check_drag_drop(drag_section(GOOD_ITEMS, buckets=("const", ""))) == [
        "dragandropp.correctpairs must be a list of bucket names"
    ]


def test_drag_drop_duplicate_ids_and_non_object_item():
    section = drag_section(GOOD_ITEMS)
    section["items"][1]["id"] = "1"
    section["items"].append("not an object")

    assert mw.check_drag_drop(section) == [
        "dragandropp.items[2] is not an object",
        "dragandropp item ids must be unique",
    ]


def test_drag_drop_item_naming_its_bucket_gives_answer_away():
    errors = mw.check_drag_drop(drag_section([("Use const for this", "const"), *GOOD_ITEMS[1:]]))

    assert errors == ["dragandropp.items[0] content names its bucket 'const'"]


def test_drag_drop_ambiguous_bucket_word_is_allowed():
    section = drag_section(
        [("A phone number", "number"), ("A user's name", "string")], ("number", "string")
    )

    assert mw.check_drag_drop(section) == []


# ---------------------------------------------------------------------------
# Card matching
# ---------------------------------------------------------------------------


def card_section(pairs):
    cards, matches = [], []
    for number, (term, description) in enumerate(pairs):
        term_id, description_id = str(2 * number + 1), str(2 * number + 2)
        cards += [{"id": term_id, "content": term}, {"id": description_id, "content": description}]
        matches.append({"card1Id": term_id, "card2Id": description_id})
    return {"cards": cards, "matches": matches}


GOOD_PAIRS = [("const", "Cannot be reassigned"), ("let", "Block scoped and reassignable")]


def test_card_matching_valid():
    assert mw.check_card_matching(card_section(GOOD_PAIRS)) == []


@pytest.mark.parametrize("term", ["n => n * 2", "const { a: { b } } = obj", "cond ? a : b"])
def test_card_matching_long_code_term_is_allowed(term):
    assert mw.check_card_matching(card_section([(term, "A short form"), *GOOD_PAIRS])) == []


def test_card_matching_plain_term_longer_than_four_words():
    errors = mw.check_card_matching(
        card_section([("one two three four five", "Words"), *GOOD_PAIRS])
    )

    assert errors == [
        "cardmatching.matches[0] term 'one two three four five' has more than 4 words"
    ]


def test_card_matching_description_names_its_term():
    errors = mw.check_card_matching(
        card_section([("const", "Use const for constants"), GOOD_PAIRS[1]])
    )

    assert errors == ["cardmatching.matches[0] description names its own term 'const'"]


def test_card_matching_identical_cards_and_repeated_terms():
    errors = mw.check_card_matching(card_section([("set", "set"), ("set", "A collection")]))

    assert errors == [
        "cardmatching.matches[0] has identical cards",
        "cardmatching: two pairs use the same term",
    ]


def test_card_matching_id_problems():
    section = card_section(GOOD_PAIRS)
    section["cards"].append({"id": "1", "content": "duplicate"})
    section["cards"].append({"id": "9", "content": "unused"})
    section["cards"].append("not an object")
    section["matches"] += [{"card1Id": "7", "card2Id": "7"}, "not an object"]

    assert mw.check_card_matching(section) == [
        "cardmatching card id '1' is used more than once",
        "cardmatching.cards[6] is not an object",
        "cardmatching.matches[2] pairs a card with itself",
        "cardmatching.matches[2] refers to unknown card id '7'",
        "cardmatching.matches[2] refers to unknown card id '7'",
        "cardmatching.matches[3] is not an object",
        "cardmatching: a card appears in more than one match",
        "cardmatching: these card ids are not in any match: 9",
    ]


@pytest.mark.parametrize("section", [None, {"cards": [], "matches": None}])
def test_card_matching_missing_section_is_left_to_schema(section):
    assert mw.check_card_matching(section) == []


# ---------------------------------------------------------------------------
# Mermaid diagrams
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("line", "edge"),
    [
        ('A["x"] --> B["y"]', ("A", "B")),
        ('A["x"] -- yes --> B["y"]', ("A", "B")),
        ('A["x"] -- no (just side effects) --> B["y"]', ("A", "B")),
        ('A["x"] -->|yes| B["y"]', ("A", "B")),
        ('A["x"] -.-> B["y"]', ("A", "B")),
        ('A["x"] -. maybe .-> B["y"]', ("A", "B")),
        ('A["x"] ==> B["y"]', ("A", "B")),
        ('A["x"] == always ==> B["y"]', ("A", "B")),
    ],
    ids=[
        "plain",
        "label",
        "label-with-brackets",
        "pipe",
        "dotted",
        "dotted-label",
        "thick",
        "thick-label",
    ],
)
def test_parse_mermaid_arrow_forms(line, edge):
    assert mw.parse_mermaid(["flowchart TD", line]) == ({"A", "B"}, [edge])


def test_parse_mermaid_chain_and_quoted_brackets():
    nodes, edges = mw.parse_mermaid(["flowchart LR", 'A["[1,2]"] --> B["f(x)"] --> C{"ok?"}'])

    assert nodes == {"A", "B", "C"}
    assert edges == [("A", "B"), ("B", "C")]


def test_mermaid_loop_without_start_node_is_allowed():
    lines = ["flowchart LR", 'A["object"] --> B["text"]', "B --> A"]

    assert mw.check_mermaid_structure(lines, "diagram") == []


def test_mermaid_single_node_is_allowed():
    assert mw.check_mermaid_structure(["flowchart TD", 'A["only"]'], "diagram") == []


def test_mermaid_structure_errors():
    lines = ["graph TD", 'A["a"] --> B', 'C["c"]']

    assert mw.check_mermaid_structure(lines, "diagram") == [
        "diagram must start with 'flowchart TD' (or TB, LR, BT, RL)",
        "diagram uses node 'B' but never defines it",
        "diagram has disconnected nodes: C",
    ]


def test_mermaid_with_no_nodes():
    assert mw.check_mermaid_structure(["flowchart TD", "%% nothing"], "diagram") == [
        "diagram defines no nodes"
    ]


def test_flowchart_checks(lesson):
    lesson["flowchart"] = {"type": "svg", "code": " "}

    assert mw.check_flowchart(lesson["flowchart"]) == [
        'flowchart.type must be "mermaid"',
        "flowchart.code is empty",
    ]
    assert mw.check_flowchart(None) == []


# ---------------------------------------------------------------------------
# Hookline images
# ---------------------------------------------------------------------------


def hook_image(**changes):
    image = {
        "status": "included",
        "style": "diagram",
        "prompt": "",
        "alt": "A diagram",
        "html": mermaid_block("flowchart TD", 'A["a"] --> B["b"]'),
    }
    image.update(changes)
    return image


def test_hook_image_valid():
    assert mw.check_hook_image(hook_image()) == []
    assert mw.check_hook_image(None) == []


def test_hook_image_field_rules():
    image = hook_image(status="generated", style="photo", prompt="draw it", alt=" ")

    assert mw.check_hook_image(image) == [
        'hooklineimage.status must be "included"',
        'hooklineimage.style must be "diagram"',
        "hooklineimage.prompt must be an empty string for a diagram",
        "hooklineimage.alt must describe the diagram",
    ]


@pytest.mark.parametrize(
    ("html", "error"),
    [
        (
            "a picture",
            "hooklineimage.html must be a Mermaid block that starts with ```mermaid "
            "and ends with ```",
        ),
        ("```mermaid\n```", "hooklineimage.html has an empty diagram"),
    ],
)
def test_hook_image_html_problems(html, error):
    assert mw.check_hook_image(hook_image(html=html)) == [error]


def test_repair_adds_missing_mermaid_fence():
    image = hook_image(html='flowchart TD\n    A["a"] --> B["b"]')

    mw.repair_hook_image(image)

    assert image["html"] == mermaid_block("flowchart TD", '    A["a"] --> B["b"]')
    assert mw.check_hook_image(image) == []


@pytest.mark.parametrize("html", ["just words", None])
def test_repair_leaves_non_diagram_html(html):
    image = hook_image(html=html)

    mw.repair_hook_image(image)

    assert image["html"] == html


def test_hookline_item_errors_name_their_item(lesson):
    lesson["hooklines"][1]["image"]["style"] = "photo"

    assert mw.check_hookline_images(lesson) == [
        'hooklines[1] hooklineimage.style must be "diagram"'
    ]


# ---------------------------------------------------------------------------
# Syntax and parts
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("line_count", [1, 6])
def test_syntax_line_limits_pass(lesson, line_count):
    lesson["syntax"]["highlight"]["code"] = "\n".join(["x;"] * line_count)

    assert mw.check_syntax_and_parts(lesson) == []


@pytest.mark.parametrize(
    ("code", "error"),
    [
        ("\n".join(["x;"] * 7), "syntax.highlight.code must have 1 to 6 lines (got 7)"),
        ("  ", "syntax.highlight.code is empty"),
    ],
)
def test_syntax_line_limit_errors(lesson, code, error):
    lesson["syntax"]["highlight"]["code"] = code

    assert mw.check_syntax_and_parts(lesson) == [error]


def test_parts_rules(lesson):
    lesson["parts"][0]["label"] = "Step 9"
    lesson["parts"][1]["name"] = lesson["parts"][2]["name"]
    lesson["parts"][3]["name"] = ""
    lesson["parts"][4] = "not an object"

    assert mw.check_syntax_and_parts(lesson) == [
        "parts[0] label must be 'Step 1'",
        "parts[3] has no name",
        "parts[4] is not an object",
        "parts names must be unique",
    ]


# ---------------------------------------------------------------------------
# Quiz, examples, title, takeaways
# ---------------------------------------------------------------------------


def test_quiz_answer_rules(lesson):
    lesson["quiz"][0]["correctAnswer"] = "const"
    lesson["quiz"][1]["correctAnswer"] = "4"
    lesson["quiz"][2]["options"] = ["only one"]

    assert mw.check_quiz_answers(lesson) == [
        'quiz 1 correctAnswer must be an index as text, such as "0"',
        'quiz 2 correctAnswer "4" is outside its 4 options',
        "quiz 3 needs at least 2 options",
    ]


def test_example_titles_must_be_numbered_in_order(lesson):
    lesson["example"][0]["title"], lesson["example"][1]["title"] = (
        lesson["example"][1]["title"],
        lesson["example"][0]["title"],
    )

    assert mw.check_example_titles(lesson) == [
        "example 1 title must start with 'Example 1:'",
        "example 2 title must start with 'Example 2:'",
    ]


@pytest.mark.parametrize("title", ["Lesson 1: Variables", "1. Variables", "2) Variables"])
def test_lesson_title_without_number_prefix(lesson, title):
    lesson["title"] = title

    assert mw.check_lesson_title(lesson) == [
        f"lesson title '{title}' must not start with 'Lesson' or a number"
    ]


def test_key_takeaway_prefixes(lesson):
    lesson["keyTakeaways"][4] = "Common Mistake: written without the emoji is fine."
    assert mw.check_key_takeaways(lesson) == []

    lesson["keyTakeaways"][4] = "A mistake."
    lesson["keyTakeaways"][5] = "A tip."
    assert mw.check_key_takeaways(lesson) == [
        "keyTakeaways item 5 must start with '⚠️ Common Mistake:'",
        "keyTakeaways item 6 must start with '💡 Pro Tip:'",
    ]


def test_missing_lists_are_left_to_schema():
    empty = {}

    assert mw.check_quiz_answers(empty) == []
    assert mw.check_example_titles(empty) == []
    assert mw.check_key_takeaways(empty) == []
    assert mw.check_hookline_images(empty) == []
    assert mw.check_syntax_and_parts(empty) == []
