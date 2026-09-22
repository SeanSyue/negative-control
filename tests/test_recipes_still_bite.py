"""The recipe check: it must pass on healthy recipes and fail on every kind
of rot - and say which recipe rotted."""
from __future__ import annotations

import json
from pathlib import Path

import pytest

import negative_control as nc

EXAMPLE = Path(__file__).resolve().parents[1] / "example"


def test_the_example_recipes_still_find_what_they_break():
    assert nc.check_recipes(EXAMPLE) == []


def test_the_example_has_recipes_and_they_live_in_one_place():
    """An empty recipe folder would make the test above pass forever."""
    assert nc.recipe_files(EXAMPLE)
    assert nc.stray_recipes(EXAMPLE) == []


HEALTHY = {
    "label": "SENTINEL",
    "file": "pricing.py",
    "replace": "if total >= FREE_SHIPPING_FROM:",
    "with": "if total > FREE_SHIPPING_FROM:",
    "test": "tests/test_pricing.py::test_an_order_of_exactly_100_ships_free",
}


@pytest.mark.parametrize(
    "rot",
    [
        pytest.param({"replace": "text that is in no file :: sentinel"}, id="text-gone"),
        pytest.param({"file": "does_not_exist.py"}, id="file-gone"),
        pytest.param({"test": "tests/test_pricing.py::test_renamed_away"}, id="test-renamed"),
        pytest.param({"with": None}, id="changes-nothing"),
    ],
)
def test_the_check_itself_has_teeth(tmp_path, rot):
    """A rot check that stays green when it should fail is the very thing this
    tool exists to catch. Every shape of rot must be reported, by name."""
    good = tmp_path / "mutations_sentinel.json"
    good.write_text(json.dumps([HEALTHY]), encoding="utf-8")
    assert nc.check_recipes(EXAMPLE, [good]) == []

    broken = dict(HEALTHY)
    for key, value in rot.items():
        broken[key] = HEALTHY["replace"] if value is None else value
    bad = tmp_path / "mutations_rotted.json"
    bad.write_text(json.dumps([broken]), encoding="utf-8")

    problems = nc.check_recipes(EXAMPLE, [bad])
    assert problems, f"rot was not reported: {broken}"
    assert any("SENTINEL" in p for p in problems), problems
