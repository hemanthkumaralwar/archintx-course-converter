"""Tests for converter/checkpoint.py: saving and reloading the course plan."""

import json

import pytest

from converter.checkpoint import load_plan, save_plan
from converter.exceptions import CheckpointError
from converter.user_input import make_request
from tests.sample_course import plan_answer


@pytest.fixture
def request_2x2(tmp_path):
    return make_request("Spike", "beginner", 2, lessons_per_module=2, output_root=tmp_path)


def write_plan(request, data):
    request.plan_file.parent.mkdir(parents=True, exist_ok=True)
    request.plan_file.write_text(json.dumps(data), encoding="utf-8")


def test_saved_plan_loads_back(request_2x2):
    modules = plan_answer()["modules"]
    save_plan(request_2x2.plan_file, request_2x2, modules)

    assert load_plan(request_2x2.plan_file, request_2x2) == modules


def broken_module_plan(request):
    modules = plan_answer()["modules"]
    modules[1]["lessons"] = ["only one"]
    return {"request": request.as_dict(), "modules": modules}


@pytest.mark.parametrize(
    ("make_data", "message"),
    [
        (lambda request: [], "must contain a JSON object"),
        (lambda request: {"modules": []}, "missing 'request'"),
        (lambda request: {"request": request.as_dict()}, "missing 'modules'"),
        (lambda request: {"request": {"title": "Other"}, "modules": []}, "different title"),
        (lambda request: {"request": request.as_dict(), "modules": []}, "must contain 2 modules"),
        (broken_module_plan, "Module 2 in the saved plan is incomplete"),
    ],
    ids=["not-object", "no-request", "no-modules", "other-course", "wrong-count", "short-module"],
)
def test_unusable_plan_is_refused(request_2x2, make_data, message):
    write_plan(request_2x2, make_data(request_2x2))

    with pytest.raises(CheckpointError, match=message):
        load_plan(request_2x2.plan_file, request_2x2)
