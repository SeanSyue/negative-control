"""The tool may only change files inside the project it was pointed at.

An earlier version joined a recipe's `file` onto the root unchecked. `../x`,
an absolute path, or a junction inside the project made it write outside -
and its cache cleanup deleted `.pyc` files outside too. Every case below puts
a sentinel outside the project and checks it is exactly as it was.
"""
from __future__ import annotations

import os
import sys
from pathlib import Path

import pytest

import negative_control as nc

ORIGINAL = "def limit():\n    return 10\n"


def _link_dir(link: Path, target: Path) -> None:
    """A directory link that needs no admin rights: a junction on Windows."""
    if os.name == "nt":
        import _winapi

        _winapi.CreateJunction(str(target), str(link))
    else:
        link.symlink_to(target, target_is_directory=True)


@pytest.fixture
def layout(tmp_path):
    project = tmp_path / "project"
    outside = tmp_path / "outside"
    project.mkdir()
    outside.mkdir()
    (project / "pytest.ini").write_text("[pytest]\npythonpath = .\n", encoding="utf-8")
    (project / "test_ok.py").write_text("def test_ok():\n    assert True\n", encoding="utf-8")
    sentinel = outside / "rule.py"
    sentinel.write_text(ORIGINAL, encoding="utf-8")
    return project, outside, sentinel


def _break(file: str) -> nc.Mutation:
    return nc.Mutation(file=file, replace="return 10", with_="return 11",
                       test="test_ok.py", label="outside")


def _run(project: Path, file: str) -> str:
    verdict, detail = nc.run_one(_break(file), root=project, python=sys.executable)
    return verdict


def test_a_path_that_climbs_out_is_refused(layout):
    project, _, sentinel = layout
    assert _run(project, "../outside/rule.py") == "broken"
    assert sentinel.read_text(encoding="utf-8") == ORIGINAL


def test_an_absolute_path_is_refused(layout):
    project, _, sentinel = layout
    assert _run(project, str(sentinel)) == "broken"
    assert sentinel.read_text(encoding="utf-8") == ORIGINAL


def test_a_junction_inside_the_project_cannot_lead_outside(layout):
    project, outside, sentinel = layout
    _link_dir(project / "src", outside)
    assert _run(project, "src/rule.py") == "broken"
    assert sentinel.read_text(encoding="utf-8") == ORIGINAL


def test_a_hard_link_to_an_outside_file_is_refused(layout):
    project, _, sentinel = layout
    os.link(sentinel, project / "rule.py")
    assert _run(project, "rule.py") == "broken"
    assert sentinel.read_text(encoding="utf-8") == ORIGINAL


def test_a_cache_folder_that_leads_outside_is_not_cleaned(layout):
    """The target is inside; only its __pycache__ is a junction to elsewhere."""
    project, outside, _ = layout
    (project / "rule.py").write_text(ORIGINAL, encoding="utf-8")
    foreign_cache = outside / "cache"
    foreign_cache.mkdir()
    foreign_pyc = foreign_cache / "rule.cpython-314.pyc"
    foreign_pyc.write_bytes(b"not ours")
    _link_dir(project / "__pycache__", foreign_cache)

    assert _run(project, "rule.py") == "broken"
    assert foreign_pyc.read_bytes() == b"not ours"
    assert (project / "rule.py").read_text(encoding="utf-8") == ORIGINAL


def test_a_plain_file_inside_still_works(layout):
    project, _, _ = layout
    (project / "rule.py").write_text(ORIGINAL, encoding="utf-8")
    (project / "test_rule.py").write_text(
        "from rule import limit\n\n\ndef test_limit():\n    assert limit() == 10\n",
        encoding="utf-8",
    )
    mutation = nc.Mutation(file="rule.py", replace="return 10", with_="return 11",
                           test="test_rule.py", label="inside")
    verdict, _ = nc.run_one(mutation, root=project, python=sys.executable)
    assert verdict == "red"
    assert (project / "rule.py").read_text(encoding="utf-8") == ORIGINAL


def test_the_recipe_check_reports_an_outside_target(layout):
    project, _, _ = layout
    (project / "mutations").mkdir()
    (project / "mutations" / "mutations_x.json").write_text(
        '[{"label": "SENTINEL", "file": "../outside/rule.py", "replace": "return 10",'
        ' "with": "return 11", "test": "test_ok.py"}]',
        encoding="utf-8",
    )
    problems = nc.check_recipes(project)
    assert any("SENTINEL" in p and "climbs out" in p for p in problems), problems
